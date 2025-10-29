import os
import boto3
from typing import List

from helpers import wait_until


REGION = os.environ.get('REGION', 'ca-central-1')
CLUSTER_NAME = os.environ['CLUSTER_NAME']

session = boto3.Session(region_name=REGION)
# eks_client = session.client('eks')
ec2_client = session.client('ec2')
# iam_client = session.client('iam')
elb_client = session.client('elb')

aws_account_id = boto3.client('sts').get_caller_identity().get('Account')

response = ec2_client.describe_vpcs(Filters=[{'Name': f'tag:cluster_name', 'Values': [CLUSTER_NAME]}])
vpc_ids = [vpc['VpcId'] for vpc in response['Vpcs']]
for vpc_id in vpc_ids:
    print("VPC ID:", vpc_id, ", deleting associated load balancers...")
    load_balancers = elb_client.describe_load_balancers()['LoadBalancerDescriptions']

    for lb in load_balancers:
        if lb['VPCId'] == vpc_id:
            load_balancer_name = lb['LoadBalancerName']
            print("Deleting load balancer:", load_balancer_name)
            response = elb_client.delete_load_balancer(LoadBalancerName=load_balancer_name)
            print(response)
            assert response['ResponseMetadata']['HTTPStatusCode'] == 200
            break

    # 1. Disassociate and release Elastic IPs linked to the VPC
    enins = ec2_client.describe_network_interfaces(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    for eni in enins["NetworkInterfaces"]:
        assoc = eni.get("Association")
        if assoc and "PublicIp" in assoc:
            print("Disassociating", assoc["PublicIp"])
            if "AssociationId" in assoc:
                ec2_client.disassociate_address(AssociationId=assoc["AssociationId"])

    # Also check for Elastic IPs not tied to ENIs directly
    eips = ec2_client.describe_addresses()["Addresses"]
    for eip in eips:
        if eip.get("AssociationId"):
            print("Releasing EIP", eip["PublicIp"])
            ec2_client.disassociate_address(AssociationId=eip["AssociationId"])
        if eip.get("AllocationId"):
            ec2_client.release_address(AllocationId=eip["AllocationId"])

    # 2. Delete NAT Gateways in the VPC (they block IGW deletion)
    ngws = ec2_client.describe_nat_gateways(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    for ngw in ngws.get("NatGateways", []):
        ngw_id = ngw["NatGatewayId"]
        print("Deleting NAT Gateway", ngw_id)
        ec2_client.delete_nat_gateway(NatGatewayId=ngw_id)

        # Wait until NAT gateway is deleted
        wait_until(
            check=ec2_client.describe_nat_gateways,
            kwargs={"NatGatewayIds": [ngw_id]},
            cond=lambda res: all(g["State"] == "deleted" for g in res.get("NatGateways", [])),
            timeout=60,
            wait_interval=2,
        )

    response = ec2_client.describe_internet_gateways()
    ids = []
    for ig in response['InternetGateways']:
        for attachment in ig.get('Attachments', []):
            if attachment.get('VpcId', '') == vpc_id:
                igw_id = ig['InternetGatewayId']
                ec2_client.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
                print(response['ResponseMetadata'])
                wait_until(
                    check=ec2_client.describe_internet_gateways,
                    kwargs={"InternetGatewayIds": [igw_id]},
                    cond=lambda res: es.get("InternetGateways", []) == [] or all(g["Attachments"] == [] for g in res.get("InternetGateways", [])),
                    timeout=60,
                    wait_interval=2,
                )
                print("Deleting Internet Gateway:", igw_id)
                ec2_client.delete_internet_gateway(InternetGatewayId=igw_id)
                print(response['ResponseMetadata'])
                wait_until(
                    check=ec2_client.describe_internet_gateways,
                    kwargs={"InternetGatewayIds": [igw_id]},
                    cond=lambda res: all(g["State"] == "deleted" for g in res.get("InternetGateways", [])),
                    timeout=60,
                    wait_interval=2,
                )

    response = ec2_client.describe_security_groups(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
    ids = []
    for sg in response['SecurityGroups']:
        if sg['GroupName'] != 'default':
            security_group_id = sg['GroupId']
            response = ec2_client.delete_security_group(GroupId=security_group_id)
            print(response['ResponseMetadata'])