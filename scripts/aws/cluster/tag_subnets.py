import argparse
import json
import os
import boto3

def tag_subnets(outputs_file):
    with open(outputs_file) as f:
        data = json.load(f)

    # account_id = os.environ["AWS_ACCOUNT_ID"]
    region = data["region"]
    cluster_name = data["cluster_name"]
    subnet_ids = data["public_subnet_ids"]

    ec2 = boto3.client("ec2", region_name=region)
    tag_key = f"kubernetes.io/cluster/{cluster_name}"

    # subnet_arns = [f"arn:aws:ec2:{region}:{account_id}:subnet/{sid}" for sid in subnet_ids]

    ec2.create_tags(
        Resources=subnet_ids,
        Tags=[{"Key": tag_key, "Value": "owned"}],
    )

    print(f"Tagged subnets: {len(subnet_ids)} with {tag_key}=owned")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tag public subnets from Pulumi output with cluster name.")
    parser.add_argument("outputs_file", help="Path to Pulumi outputs JSON file.")
    args = parser.parse_args()

    tag_subnets(args.outputs_file)
