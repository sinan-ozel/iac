import boto3
from typing import List

REGION = os.environ.get('REGION', 'ca-central-1')
CLUSTER_NAME = os.environ['CLUSTER_NAME']

session = boto3.Session(region_name=REGION)
eks_client = session.client('eks')
ec2_client = session.client('ec2')
iam_client = session.client('iam')

aws_account_id = boto3.client('sts').get_caller_identity().get('Account')

response = ec2_client.describe_vpcs(Filters=[{'Name': f'tag:cluster_name', 'Values': [CLUSTER_NAME]}])
vpc_ids = [vpc['VpcId'] for vpc in response['Vpcs']]
assert len(vpc_ids) == 1
vpc_id = vpc_ids[0]
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

