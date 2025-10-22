import boto3
import argparse
import os
import fnmatch

# Ensure required env vars are set
REGION = os.environ.get("REGION")
ORG = os.environ.get("GITHUB_ORGANIZATION_NAME")
if not REGION or not ORG:
    raise RuntimeError("Both REGION and GITHUB_ORGANIZATION_NAME must be set.")

iam = boto3.client("iam", region_name=REGION)

def main(cluster_name, repo_name):
    role_pattern = f"{cluster_name}-{ORG}-{repo_name}-admin-role"
    policy_pattern = f"{cluster_name}-{repo_name}-scoped-*"

    # Delete roles
    for role in iam.list_roles()["Roles"]:
        name = role["RoleName"]
        if name == role_pattern:
            print(f"Cleaning role {name}")
            # Detach inline and attached policies
            for p in iam.list_attached_role_policies(RoleName=name)["AttachedPolicies"]:
                iam.detach_role_policy(RoleName=name, PolicyArn=p["PolicyArn"])
            for p in iam.list_role_policies(RoleName=name)["PolicyNames"]:
                iam.delete_role_policy(RoleName=name, PolicyName=p)
            iam.delete_role(RoleName=name)

    # Delete policies
    for policy in iam.list_policies(Scope="Local")["Policies"]:
        if fnmatch.fnmatch(policy["PolicyName"], policy_pattern):
            arn = policy["Arn"]
            print(f"Deleting policy {policy['PolicyName']}")
            # Delete old versions first
            versions = iam.list_policy_versions(PolicyArn=arn)["Versions"]
            for v in versions:
                if not v["IsDefaultVersion"]:
                    iam.delete_policy_version(PolicyArn=arn, VersionId=v["VersionId"])
            iam.delete_policy(PolicyArn=arn)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--repo-name", required=True)
    args = parser.parse_args()
    main(args.cluster_name, args.repo_name)
