import os
import sys
import json
import argparse
import boto3
import copy


def get_policy_template(template_path, substitutions):
    """Load a JSON template and replace placeholders with substitutions."""
    with open(template_path) as f:
        policy = json.load(f)

    def replace(obj):
        if isinstance(obj, dict):
            return {k: replace(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [replace(v) for v in obj]
        elif isinstance(obj, str):
            for key, value in substitutions.items():
                obj = obj.replace(f"${{{key}}}", value)
            return obj
        else:
            return obj

    return replace(policy)


def create_scoped_managed_policy(iam_client, managed_policy_arn, account_id, cluster_name):
    """
    Reads the AWS-managed policy, scopes its resources to the cluster, and returns it.

    Note: This function assumes the managed policy uses wildcard resources that can be scoped.

    1. Fetch the managed policy document.
    2. Modify the "Resource" fields to restrict access to the specific EKS cluster
         (e.g., replace "*" with "arn
    """
    print(f"Reading managed policy {managed_policy_arn}")
    version = iam_client.get_policy(PolicyArn=managed_policy_arn)["Policy"]["DefaultVersionId"]
    policy_doc = iam_client.get_policy_version(
        PolicyArn=managed_policy_arn, VersionId=version
    )["PolicyVersion"]["Document"]

    scoped_policy = copy.deepcopy(policy_doc)
    cluster_arn = f"arn:aws:eks:*:{account_id}:*/{cluster_name}*"

    def scope_resource(obj):
        """Recursively replace '*' with cluster ARN"""
        if isinstance(obj, str):
            return cluster_arn if obj.strip() == "*" else obj
        elif isinstance(obj, list):
            return [scope_resource(x) for x in obj]
        elif isinstance(obj, dict):
            return {k: scope_resource(v) for k, v in obj.items()}
        else:
            return obj

    # Apply scoping only to Resource fields in statements
    for stmt in scoped_policy.get("Statement", []):
        if "Resource" in stmt:
            stmt["Resource"] = scope_resource(stmt["Resource"])

    return scoped_policy


def main():
    parser = argparse.ArgumentParser(description="Create EKS admin role for repo/cluster")
    parser.add_argument("--cluster-name", required=True, help="EKS cluster name")
    parser.add_argument("--repo-name", required=True, help="GitHub repo name")
    args = parser.parse_args()

    REGION = os.environ.get("AWS_REGION")
    if not REGION:
        sys.exit("ERROR: AWS_REGION environment variable is not set. Please set it before running the container.")
    GITHUB_ORGANIZATION_NAME = os.environ.get("GITHUB_ORGANIZATION_NAME")
    if not GITHUB_ORGANIZATION_NAME:
        sys.exit("ERROR: GITHUB_ORGANIZATION_NAME environment variable is not set. Please set it before running the container.")

    session = boto3.Session(region_name=REGION)

    iam_client = session.client("iam")
    sts_client = session.client("sts")

    aws_account_id = sts_client.get_caller_identity()["Account"]



    role_name = f"{args.cluster_name}-{GITHUB_ORGANIZATION_NAME}-{args.repo_name}-admin-role"

    # Trust policy (GitHub OIDC example)
    trust_template_path = "policies/trust_policy.json"
    trust_policy = get_policy_template(
        trust_template_path,
        {
            "ACCOUNT_ID": aws_account_id,
            "ORG_NAME": GITHUB_ORGANIZATION_NAME,
            "REPO_NAME": args.repo_name
        },
    )

    print(f"Creating role {role_name}...")
    try:
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=f"Admin role for cluster {args.cluster_name} and repo {args.repo_name}"
        )
    except iam_client.exceptions.EntityAlreadyExistsException:
        print(f"Role {role_name} already exists.")

    # Attach AWS managed policies
    managed_policies = [
        "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
        "arn:aws:iam::aws:policy/AmazonEKSServicePolicy",
        "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
    ]

    for managed_arn in managed_policies:
        scoped_policy_doc = create_scoped_managed_policy(iam_client, managed_arn, aws_account_id, args.cluster_name)
        policy_name = f"{args.cluster_name}-{GITHUB_ORGANIZATION_NAME}-{args.repo_name}-scoped-{managed_arn.split('/')[-1]}"
        print(f"Creating scoped policy {policy_name}")
        print(json.dumps(scoped_policy_doc, indent=2))
        try:
            iam_client.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(scoped_policy_doc),
                Description=f"Scoped policy derived from {managed_arn} for cluster {args.cluster_name}"
            )
        except iam_client.exceptions.EntityAlreadyExistsException:
            print(f"Policy {policy_name} already exists.")
        # Attach scoped policy to role
        iam_client.attach_role_policy(RoleName=role_name, PolicyArn=f"arn:aws:iam::{aws_account_id}:policy/{policy_name}")
        print(f"Attached {policy_name} to {role_name}")

    # Custom inline policy (template substitution)
    custom_template_path = "policies/custom_policy.json"
    custom_policy = get_policy_template(
        custom_template_path,
        {
            "ACCOUNT_ID": aws_account_id,
            "CLUSTER_NAME": args.cluster_name,
            "REPO_NAME": args.repo_name
        },
    )

    policy_name = f"{args.cluster_name}-{GITHUB_ORGANIZATION_NAME}-{args.repo_name}-custom-inline-policy"
    print(f"Putting inline policy {policy_name}")
    print(json.dumps(custom_policy, indent=2))
    iam_client.put_role_policy(
        RoleName=role_name,
        PolicyName=policy_name,
        PolicyDocument=json.dumps(custom_policy)
    )

    print(f"✅ Role {role_name} setup complete.")

if __name__ == "__main__":
    main()
