import os
import boto3
from typing import List
from time import sleep

from helpers import wait_until


REGION = os.environ.get('REGION', 'ca-central-1')
CLUSTER_NAME = os.environ['CLUSTER_NAME']

session = boto3.Session(region_name=REGION)
# eks_client = session.client('eks')
ec2_client = session.client('ec2')
# iam_client = session.client('iam')
elb_client = session.client('elb')
elbv2_client = session.client('elbv2')  # Application/Network Load Balancers

aws_account_id = boto3.client('sts').get_caller_identity().get('Account')

response = ec2_client.describe_vpcs(Filters=[{'Name': f'tag:cluster_name', 'Values': [CLUSTER_NAME]}])
vpc_ids = [vpc['VpcId'] for vpc in response['Vpcs']]
for vpc_id in vpc_ids:
    print("VPC ID:", vpc_id, ", deleting associated load balancers...")

    v2_load_balancers = elbv2_client.describe_load_balancers()['LoadBalancers']
    deleted_lb_arns: List[str] = []

    for lb in v2_load_balancers:
        if lb['VpcId'] == vpc_id:
            lb_arn = lb['LoadBalancerArn']
            lb_name = lb['LoadBalancerName']
            print(f"Deleting ALB/NLB: {lb_name}")
            response = elbv2_client.delete_load_balancer(LoadBalancerArn=lb_arn)
            print(response)
            assert response['ResponseMetadata']['HTTPStatusCode'] == 200
            deleted_lb_arns.append(lb_arn)
            print(f"Deleted {lb_name}")

    def check_lbs_deleted(res):
        # If LoadBalancerNotFoundException is raised, it means they're all deleted
        # Otherwise check if the list is empty
        return

    wait_until(
        check=elbv2_client.describe_load_balancers,
        kwargs={"LoadBalancerArns": deleted_lb_arns},
        cond=lambda x: len(x.get('LoadBalancers', [])) == 0,
        timeout=300,
        wait_interval=10,
    )

    # 1. Delete NAT Gateways in the VPC (they block IGW deletion)
    ngws = ec2_client.describe_nat_gateways(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    nat_gateway_ids = []
    for ngw in ngws.get("NatGateways", []):
        ngw_id = ngw["NatGatewayId"]
        print("Deleting NAT Gateway", ngw_id)
        nat_gateway_ids.append(ngw_id)
        ec2_client.delete_nat_gateway(NatGatewayId=ngw_id)

    # Wait for ALL NAT gateways to be deleted
    if nat_gateway_ids:
        print(f"Waiting for {len(nat_gateway_ids)} NAT Gateway(s) to be fully deleted...")
        for ngw_id in nat_gateway_ids:
            print(f"Waiting for NAT Gateway {ngw_id}...")
            wait_until(
                check=ec2_client.describe_nat_gateways,
                kwargs={"NatGatewayIds": [ngw_id]},
                cond=lambda res: all(g["State"] == "deleted" for g in res.get("NatGateways", [])),
                timeout=300,
                wait_interval=10,
            )
            print(f"NAT Gateway {ngw_id} deleted")

        print("All NAT Gateways deleted. Waiting additional 30 seconds for EIP cleanup...")
        sleep(30)

    # 2. Find and release ALL Elastic IPs in the VPC
    print("Checking for Elastic IPs in the VPC...")
    enins = ec2_client.describe_network_interfaces(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    eip_released = False

    for eni in enins["NetworkInterfaces"]:
        assoc = eni.get("Association")
        if assoc and "PublicIp" in assoc:
            public_ip = assoc["PublicIp"]
            eni_id = eni["NetworkInterfaceId"]
            print(f"Found EIP {public_ip} on network interface {eni_id}")

            # Check what's using this ENI
            attachment = eni.get("Attachment", {})
            instance_id = attachment.get("InstanceId")
            if instance_id:
                print(f"  - Attached to EC2 instance: {instance_id}")

            requester_id = eni.get("RequesterId")
            print(f"  - Requester: {requester_id}")
            print(f"  - Status: {eni.get('Status')}")

            # If the ENI is available (not attached), we can try to delete it
            if eni.get("Status") == "available":
                try:
                    print(f"  - Deleting available network interface {eni_id}")
                    ec2_client.delete_network_interface(NetworkInterfaceId=eni_id)
                    eip_released = True
                except Exception as e:
                    print(f"  - Could not delete ENI: {e}")

    # 3. Also check for standalone Elastic IPs
    all_eips = ec2_client.describe_addresses()["Addresses"]
    for eip in all_eips:
        # Check if this EIP is in our VPC
        if "NetworkInterfaceId" in eip:
            try:
                eni_info = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eip["NetworkInterfaceId"]])
                if eni_info["NetworkInterfaces"] and eni_info["NetworkInterfaces"][0].get("VpcId") == vpc_id:
                    print(f"Found standalone EIP {eip.get('PublicIp')} associated with VPC")
                    print(f"  - Association ID: {eip.get('AssociationId')}")
                    print(f"  - Network Interface: {eip.get('NetworkInterfaceId')}")
            except:
                pass

    if eip_released:
        print("Waiting 30 seconds for EIP cleanup to propagate...")
        sleep(30)
