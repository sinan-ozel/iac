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

    # Delete Classic Load Balancers (ELBv1)
    classic_lbs = elb_client.describe_load_balancers()['LoadBalancerDescriptions']
    deleted_classic_lb_names: List[str] = []

    for lb in classic_lbs:
        if lb['VPCId'] == vpc_id:
            lb_name = lb['LoadBalancerName']
            print(f"Deleting Classic ELB: {lb_name}")
            response = elb_client.delete_load_balancer(LoadBalancerName=lb_name)
            print(response)
            assert response['ResponseMetadata']['HTTPStatusCode'] == 200
            deleted_classic_lb_names.append(lb_name)
            print(f"Deleted Classic ELB {lb_name}")

    # Wait for classic LBs to be deleted
    if deleted_classic_lb_names:
        print(f"Waiting for {len(deleted_classic_lb_names)} Classic ELB(s) to be deleted...")
        for lb_name in deleted_classic_lb_names:
            # Keep checking if the LB still exists in the full list
            all_lbs = elb_client.describe_load_balancers()['LoadBalancerDescriptions']
            remaining_names = [lb['LoadBalancerName'] for lb in all_lbs]

            if lb_name in remaining_names:
                wait_until(
                    check=lambda: [lb['LoadBalancerName'] for lb in elb_client.describe_load_balancers()['LoadBalancerDescriptions']],
                    kwargs={},
                    cond=lambda x: lb_name not in x,
                    timeout=300,
                    wait_interval=10,
                )
        print(f"All Classic ELBs deleted")

    # Delete ALB/NLB (ELBv2)
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

    # Delete security groups created by Kubernetes/Helm for load balancers
    print("Checking for Kubernetes-managed security groups...")
    all_sgs = ec2_client.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    k8s_elb_sgs = []

    for sg in all_sgs['SecurityGroups']:
        sg_name = sg.get('GroupName', '')
        sg_id = sg['GroupId']

        # Check if this is a k8s-managed ELB security group (NOT cluster or node SGs)
        if sg_name.startswith('k8s-elb-'):
            # Skip default SG and cluster/node security groups
            if sg_name == 'default' or 'eks-cluster-sg' in sg_name or 'nodeSecurityGroup' in sg_name:
                continue

            print(f"Found Kubernetes ELB security group: {sg_name} ({sg_id})")
            k8s_elb_sgs.append(sg_id)

    # Delete the security groups (need to wait for LBs to be fully deleted first)
    if k8s_elb_sgs:
        print(f"Waiting for load balancers and network interfaces to be fully cleaned up...")
        wait_until(
            check=lambda: ec2_client.describe_network_interfaces(
                Filters=[{"Name": "group-id", "Values": k8s_elb_sgs}]
            ),
            kwargs={},
            cond=lambda res: len(res.get('NetworkInterfaces', [])) == 0,
            timeout=300,
            wait_interval=10,
        )

        for sg_id in k8s_elb_sgs:
            print(f"Deleting security group {sg_id}")

            # Step 1: Check for instances using this security group
            print(f"  - Checking for instances associated with security group {sg_id}")
            instances_response = ec2_client.describe_instances(
                Filters=[{"Name": "instance.group-id", "Values": [sg_id]}]
            )

            instance_ids = []
            for reservation in instances_response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    instance_id = instance['InstanceId']
                    instance_state = instance['State']['Name']
                    instance_ids.append(instance_id)
                    print(f"    - Found instance {instance_id} (state: {instance_state})")

                    # Modify instance to remove this security group
                    current_sgs = [sg['GroupId'] for sg in instance.get('SecurityGroups', [])]
                    # Filter out the current security group we're trying to delete
                    new_sgs = [sg for sg in current_sgs if sg != sg_id]

                    if new_sgs:
                        print(f"      - Updating instance security groups from {current_sgs} to {new_sgs}")
                        ec2_client.modify_instance_attribute(
                            InstanceId=instance_id,
                            Groups=new_sgs
                        )
                        print(f"      - Disassociated security group from instance {instance_id}")
                    else:
                        print(f"      - WARNING: Instance {instance_id} only has this security group, cannot remove")

            # Step 2: Find and handle all network interfaces using this security group
            print(f"  - Finding network interfaces associated with security group {sg_id}")
            eni_response = ec2_client.describe_network_interfaces(
                Filters=[{"Name": "group-id", "Values": [sg_id]}]
            )

            for eni in eni_response.get('NetworkInterfaces', []):
                eni_id = eni['NetworkInterfaceId']
                attachment = eni.get('Attachment', {})
                eni_status = eni.get('Status')

                print(f"    - Network interface {eni_id} (status: {eni_status})")

                # Get current security groups on this ENI
                current_sgs = [sg['GroupId'] for sg in eni.get('Groups', [])]
                new_sgs = [sg for sg in current_sgs if sg != sg_id]

                # Try to modify the ENI to remove this security group
                if new_sgs:
                    print(f"      - Modifying ENI security groups from {current_sgs} to {new_sgs}")
                    ec2_client.modify_network_interface_attribute(
                        NetworkInterfaceId=eni_id,
                        Groups=new_sgs
                    )
                    print(f"      - Disassociated security group from ENI {eni_id}")
                    continue  # Don't try to delete if we just modified


                # If attached, try to detach
                if 'AttachmentId' in attachment:
                    print(f"      - Detaching network interface (Attachment: {attachment.get('AttachmentId')})")
                    ec2_client.detach_network_interface(
                        AttachmentId=attachment['AttachmentId'],
                        Force=True
                    )
                    print(f"      - Waiting for detachment...")
                    wait_until(
                        check=ec2_client.describe_network_interfaces,
                        kwargs={"NetworkInterfaceIds": [eni_id]},
                        cond=lambda res: res['NetworkInterfaces'][0].get('Attachment') is None or res['NetworkInterfaces'][0]['Status'] == 'available',
                        timeout=60,
                        wait_interval=5,
                    )
                    print(f"      - Detached {eni_id}")

                # If ENI is available or has no attachment, try to delete it
                if eni_status == 'available' or 'AttachmentId' not in attachment:
                    print(f"      - Deleting available network interface {eni_id}")
                    ec2_client.delete_network_interface(NetworkInterfaceId=eni_id)
                    print(f"      - Deleted {eni_id}")

            # Step 3: Remove all ingress and egress rules to remove cross-SG dependencies
            sg_details = ec2_client.describe_security_groups(GroupIds=[sg_id])['SecurityGroups'][0]

            if sg_details['IpPermissions']:
                print(f"  - Removing {len(sg_details['IpPermissions'])} ingress rule(s)")
                ec2_client.revoke_security_group_ingress(
                    GroupId=sg_id,
                    IpPermissions=sg_details['IpPermissions']
                )

            if sg_details['IpPermissionsEgress']:
                print(f"  - Removing {len(sg_details['IpPermissionsEgress'])} egress rule(s)")
                ec2_client.revoke_security_group_egress(
                    GroupId=sg_id,
                    IpPermissions=sg_details['IpPermissionsEgress']
                )

            # Step 3.5: Check if any OTHER security groups reference this one
            print(f"  - Checking for security groups that reference {sg_id}")
            all_vpc_sgs = ec2_client.describe_security_groups(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )['SecurityGroups']

            for other_sg in all_vpc_sgs:
                if other_sg['GroupId'] == sg_id:
                    continue  # Skip the SG we're trying to delete

                # Check if this SG references our target SG in ingress rules
                rules_to_revoke = []
                for perm in other_sg.get('IpPermissions', []):
                    for group_pair in perm.get('UserIdGroupPairs', []):
                        if group_pair.get('GroupId') == sg_id:
                            rules_to_revoke.append(perm)
                            break

                if rules_to_revoke:
                    print(f"    - Removing {len(rules_to_revoke)} rule(s) from {other_sg['GroupId']} that reference {sg_id}")
                    ec2_client.revoke_security_group_ingress(
                        GroupId=other_sg['GroupId'],
                        IpPermissions=rules_to_revoke
                    )

                # Check egress rules
                egress_rules_to_revoke = []
                for perm in other_sg.get('IpPermissionsEgress', []):
                    for group_pair in perm.get('UserIdGroupPairs', []):
                        if group_pair.get('GroupId') == sg_id:
                            egress_rules_to_revoke.append(perm)
                            break

                if egress_rules_to_revoke:
                    print(f"    - Removing {len(egress_rules_to_revoke)} egress rule(s) from {other_sg['GroupId']} that reference {sg_id}")
                    ec2_client.revoke_security_group_egress(
                        GroupId=other_sg['GroupId'],
                        IpPermissions=egress_rules_to_revoke
                    )

            # Step 4: Wait for all modifications to propagate, then delete the security group
            print(f"  - Waiting for security group modifications to propagate...")
            wait_until(
                check=lambda: ec2_client.describe_network_interfaces(
                    Filters=[{"Name": "group-id", "Values": [sg_id]}]
                ),
                kwargs={},
                cond=lambda res: len(res.get('NetworkInterfaces', [])) == 0,
                timeout=120,
                wait_interval=5,
            )
            ec2_client.delete_security_group(GroupId=sg_id)
            print(f"  - ✅ Deleted security group {sg_id}")

    # Additional cleanup: Release Elastic IPs associated with the VPC
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

            # If owned by amazon-elb, force delete the network interface
            if requester_id == "amazon-elb":
                print(f"  - Detaching and deleting ELB-owned network interface {eni_id}")
                # First, try to detach if attached
                if attachment and "AttachmentId" in attachment:
                    ec2_client.detach_network_interface(
                        AttachmentId=attachment["AttachmentId"],
                        Force=True
                    )
                    print(f"  - Detached network interface")
                    sleep(5)

                # Then delete the network interface
                ec2_client.delete_network_interface(NetworkInterfaceId=eni_id)
                print(f"  - Deleted network interface {eni_id}")
                eip_released = True

            # If the ENI is available (not attached), we can try to delete it
            elif eni.get("Status") == "available":
                print(f"  - Deleting available network interface {eni_id}")
                ec2_client.delete_network_interface(NetworkInterfaceId=eni_id)
                eip_released = True

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
