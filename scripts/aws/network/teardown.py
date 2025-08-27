import os

import boto3

from helpers import wait_until



REGION = os.environ.get('REGION', 'ca-central-1')
CLUSTER_NAME = os.environ.get('CLUSTER_NAME')
AWS_ACCOUNT_ID = os.environ.get('AWS_ACCOUNT_ID')


def get_network_interface_ids_for_vpc(vpc_id: str):
    response = ec2_client.describe_network_interfaces(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
    network_interface_ids = []
    for network_interface in response['NetworkInterfaces']:
        network_interface_ids.append(network_interface['NetworkInterfaceId'])
    return network_interface_ids


def get_security_group_ids_for_vpc(vpc_id: str) -> list[str]:
    response = ec2_client.describe_security_groups(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
    ids = []
    for sg in response['SecurityGroups']:
        if sg['GroupName'] != 'default':
            ids.append(sg['GroupId'])
    return ids


def get_internet_gateway_ids_attached_to_vpc(vpc_id: str) -> list[str]:
    response = ec2_client.describe_internet_gateways()
    ids = []
    for ig in response['InternetGateways']:
        for attachment in ig.get('Attachments', []):
            if attachment.get('VpcId', '') == vpc_id:
                ids.append(ig['InternetGatewayId'])
    return ids


def get_subnet_ids_in_vpc(vpc_id: str) -> list[str]:
    subnets_response = ec2_client.describe_subnets()
    subnet_ids = []
    for subnet in subnets_response['Subnets']:
        if subnet['VpcId'] == vpc_id:
            subnet_ids.append(subnet['SubnetId'])
    return subnet_ids


# def get_route_table_ids_for_vpc(vpc_id: str):
#     response = ec2_client.describe_route_tables()
#     rt_ids = []
#     for route_table in response['RouteTables']:
#         if route_table['VpcId'] == vpc_id:
#             rt_ids.append(route_table['RouteTableId'])
#     return rt_ids


def get_route_tables_for_vpc(vpc_id: str):
    response = ec2_client.describe_route_tables()
    rts = []
    for route_table in response['RouteTables']:
        if route_table['VpcId'] == vpc_id:
            rts.append(route_table)
    return rts


session = boto3.Session(region_name=REGION)
ec2_client = session.client('ec2')
elb_client = session.client('elb')
eks_client = session.client('eks')

try:
    node_groups = eks_client.list_nodegroups(clusterName=CLUSTER_NAME).get('nodegroups', [])
except eks_client.exceptions.ResourceNotFoundException:
    print(f"Cluster {CLUSTER_NAME} does not exist, skipping deletion.")
    node_groups = []

for node_group_name in node_groups:
    print(f"Deleting node group: {node_group_name}")
    response = eks_client.describe_nodegroup(clusterName=CLUSTER_NAME, nodegroupName=node_group_name)
    status = response['nodegroup']['status']

    eks_client.delete_nodegroup(clusterName=CLUSTER_NAME, nodegroupName=node_group_name)

    # Wait for this specific node group to be deleted
    def check_nodegroup_deleted():
        try:
            eks_client.describe_nodegroup(clusterName=CLUSTER_NAME, nodegroupName=node_group_name)
            return False  # Still exists
        except eks_client.exceptions.ResourceNotFoundException:
            return True  # Successfully deleted

    wait_until(
        check=lambda: check_nodegroup_deleted(),
        kwargs={},
        cond=lambda x: x is True,
        wait_interval=10
    )
    print(f"Node group {node_group_name} deleted successfully")

# Verify all node groups are gone with multiple checks
print("Verifying all node groups are completely deleted...")
try:
    # First check: wait for list_nodegroups to return empty
    wait_until(
        check=eks_client.list_nodegroups,
        kwargs={'clusterName': CLUSTER_NAME},
        cond=lambda x: len(x['nodegroups']) == 0,
        wait_interval=15
    )

    # Second check: verify cluster status shows no node groups
    def check_cluster_ready_for_deletion():
        try:
            cluster_info = eks_client.describe_cluster(name=CLUSTER_NAME)
            # Additional wait to ensure AWS internal state is consistent
            remaining_nodegroups = eks_client.list_nodegroups(clusterName=CLUSTER_NAME)['nodegroups']
            return len(remaining_nodegroups) == 0
        except eks_client.exceptions.ResourceNotFoundException:
            return True

    wait_until(
        check=check_cluster_ready_for_deletion,
        kwargs={},
        cond=lambda x: x is True,
        wait_interval=20
    )

except eks_client.exceptions.ResourceNotFoundException:
    print(f"Cluster {CLUSTER_NAME} no longer exists")

print("All node groups deleted and cluster ready for deletion")

try:
    eks_client.delete_cluster(name=CLUSTER_NAME)
    print(f"Cluster {CLUSTER_NAME} deletion initiated")
except eks_client.exceptions.ResourceNotFoundException:
    print(f"Cluster {CLUSTER_NAME} does not exist, skipping deletion.")
except eks_client.exceptions.ResourceInUseException:
    print(f"Cluster {CLUSTER_NAME} still has resources attached. Waiting longer...")
    # Wait additional time and try once more
    import time
    time.sleep(60)
    try:
        eks_client.delete_cluster(name=CLUSTER_NAME)
        print(f"Cluster {CLUSTER_NAME} deletion initiated after additional wait")
    except Exception as e:
        print(f"Failed to delete cluster after extended wait: {e}")

wait_until(eks_client.list_clusters, {}, lambda x: CLUSTER_NAME not in x['clusters'], wait_interval=3)

response = ec2_client.describe_vpcs(Filters=[{'Name': f'tag:purpose', 'Values': [CLUSTER_NAME]}])
vpc_ids = [vpc['VpcId'] for vpc in response['Vpcs']]
print(f"Found the following VPCs: {vpc_ids}. Deleting.")
for vpc_id in vpc_ids:
    # Delete NAT Gateways first (they hold Elastic IPs)
    nat_gateways = ec2_client.describe_nat_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
    for nat_gw in nat_gateways['NatGateways']:
        if nat_gw['State'] != 'deleted':
            print(f"Deleting NAT Gateway: {nat_gw['NatGatewayId']}")
            ec2_client.delete_nat_gateway(NatGatewayId=nat_gw['NatGatewayId'])

    # Wait for NAT Gateways to be deleted
    if nat_gateways['NatGateways']:
        print("Waiting for NAT Gateways to be deleted...")
        wait_until(
            check=lambda: ec2_client.describe_nat_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]),
            kwargs={},
            cond=lambda x: all(gw['State'] == 'deleted' for gw in x['NatGateways']),
            wait_interval=10
        )

    # Release Elastic IPs associated with the VPC
    addresses = ec2_client.describe_addresses()
    for addr in addresses['Addresses']:
        if addr.get('Domain') == 'vpc':
            # Check if this EIP is associated with any resources in our VPC
            if 'NetworkInterfaceId' in addr:
                eni = ec2_client.describe_network_interfaces(NetworkInterfaceIds=[addr['NetworkInterfaceId']])
                if eni['NetworkInterfaces'][0]['VpcId'] == vpc_id:
                    print(f"Releasing Elastic IP: {addr['AllocationId']}")
                    ec2_client.release_address(AllocationId=addr['AllocationId'])
            elif 'InstanceId' in addr:
                instance = ec2_client.describe_instances(InstanceIds=[addr['InstanceId']])
                if instance['Reservations'][0]['Instances'][0]['VpcId'] == vpc_id:
                    print(f"Releasing Elastic IP: {addr['AllocationId']}")
                    ec2_client.release_address(AllocationId=addr['AllocationId'])

    route_tables = get_route_tables_for_vpc(vpc_id)
    for route_table in route_tables:
        for route in route_table["Routes"]:
            print(route.get('GatewayId'))
            if route.get("GatewayId", "").startswith("igw-"):
                print(f"Deleting route to {route['GatewayId']} in Route Table {route_table['RouteTableId']}...")
                ec2_client.delete_route(RouteTableId=route_table["RouteTableId"], DestinationCidrBlock=route["DestinationCidrBlock"])

    wait_until(
        check=get_route_tables_for_vpc,
        kwargs={'vpc_id': vpc_id},
        cond=lambda x: len(x) == 0
    )

    network_interface_ids = get_network_interface_ids_for_vpc(vpc_id)

    enis = ec2_client.describe_network_interfaces(NetworkInterfaceIds=network_interface_ids)['NetworkInterfaces']
    for eni in enis:
        if eni['Description'].startswith('ELB'):
            lb_name = eni['Description'].split(' ')[1]
            elb_client.delete_load_balancer(LoadBalancerName=lb_name)

    igw_ids = get_internet_gateway_ids_attached_to_vpc(vpc_id)
    for igw_id in igw_ids:
        ec2_client.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)

    wait_until(
        check=get_internet_gateway_ids_attached_to_vpc,
        kwargs={'vpc_id': vpc_id},
        cond=lambda x: len(x) == 0
    )

    for igw_id in igw_ids:
        ec2_client.delete_internet_gateway(InternetGatewayId=igw_id)

    subnet_ids = get_subnet_ids_in_vpc(vpc_id)
    for subnet_id in subnet_ids:
        response = ec2_client.delete_subnet(SubnetId=subnet_id)
        print(response['ResponseMetadata'])

    wait_until(
        check=get_subnet_ids_in_vpc,
        kwargs={'vpc_id': vpc_id},
        cond=lambda x: len(x) == 0
    )

    security_group_ids_for_vpc = get_security_group_ids_for_vpc(vpc_id)
    for security_group_id in security_group_ids_for_vpc:
        response = ec2_client.delete_security_group(GroupId=security_group_id)
        print(response['ResponseMetadata'])

    wait_until(
        check=get_security_group_ids_for_vpc,
        kwargs={'vpc_id': vpc_id},
        cond=lambda x: len(x) == 0
    )

    route_tables = get_route_tables_for_vpc(vpc_id)
    for route_table in route_tables:
        associations = route_table.get('Associations', [])
        if not any(assoc.get('Main') for assoc in associations):
            ec2_client.delete_route_table(RouteTableId=route_table['RouteTableId'])

    response = ec2_client.delete_vpc(VpcId=vpc_id)
    response['ResponseMetadata']

    wait_until(
        check=ec2_client.describe_vpcs,
        kwargs={'Filters': [{'Name': f'tag:purpose', 'Values': [CLUSTER_NAME]}]},
        cond=lambda x: len(x) == 0
    )

    # route_table_ids = get_route_table_ids_for_vpc(vpc_id)
    # for route_table_id in route_table_ids:
    #     # route_table = ec2_client.describe_route_tables(RouteTableIds=[route_table_id])['RouteTables'][0]
    #     # for route in route_table['Routes']:
    #     #     if route.get('State') == 'blackhole':
    #     #         ec2_client.delete_route(RouteTableId=route_table_id, DestinationCidrBlock=route['DestinationCidrBlock'])
    #     response = ec2_client.delete_route_table(RouteTableId=route_table_id)
    #     print(response['ResponseMetadata'])
    #     print(response['ResponseMetadata'])
