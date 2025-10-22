FROM public.ecr.aws/lambda/python:3.11

RUN pip install boto3

WORKDIR /app
COPY create_eks_admin_role.py .
COPY cleanup_eks_admin_role.py .
COPY policies/ policies/

ENTRYPOINT ["python"]
