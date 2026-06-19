# AWS CI/CD Setup

## Deployment Target

FinSight-AI targets Amazon ECS on AWS Fargate. The expected production architecture is:

- Two ECS services for the frontend and backend containers.
- A separate ECS worker service when ARQ background jobs are enabled.
- An Application Load Balancer for public traffic.
- Amazon RDS for PostgreSQL with the `vector` extension.
- Amazon ElastiCache for Redis.
- Amazon S3 for durable uploaded-file storage.
- AWS Secrets Manager for application and private-registry credentials.
- Amazon CloudWatch Logs for container logs.

The workflow deploys to existing ECS services. It does not provision AWS infrastructure.

## GHCR Images

After backend tests, frontend tests, Docker builds, and Trivy scans pass on `master`, CI publishes:

- `ghcr.io/remo-dif/finsight-ai-backend:<commit-sha>`
- `ghcr.io/remo-dif/finsight-ai-frontend:<commit-sha>`
- `latest` tags for operator convenience only

ECS deployments use the immutable commit SHA tag, never `latest`.

If the GHCR packages are private, create an AWS Secrets Manager secret containing:

```json
{
  "username": "remo-dif",
  "password": "GHCR_TOKEN_WITH_READ_PACKAGES"
}
```

Reference that secret from each ECS container definition through
`repositoryCredentials.credentialsParameter`. The ECS task execution role needs
`secretsmanager:GetSecretValue` permission for the secret. Do not store the GHCR pull token in
the repository or pass it as an image build argument.

## GitHub Production Environment

Create a repository variable named `AWS_DEPLOY_ENABLED` and leave it unset or set to `false` until
the ECS infrastructure is ready. Create a GitHub environment named `production`, add approval
protection, and configure the remaining environment variables there:

| Variable | Purpose |
| --- | --- |
| `AWS_ROLE_ARN` | IAM role assumed by GitHub Actions through OIDC. |
| `AWS_REGION` | AWS region containing the ECS cluster. |
| `ECS_CLUSTER` | ECS cluster name. |
| `ECS_BACKEND_SERVICE` | Existing backend ECS service name. |
| `ECS_FRONTEND_SERVICE` | Existing frontend ECS service name. |
| `ECS_BACKEND_TASK_FAMILY` | Backend task-definition family. |
| `ECS_FRONTEND_TASK_FAMILY` | Frontend task-definition family. |
| `ECS_BACKEND_CONTAINER` | Backend container name in its task definition. |
| `ECS_FRONTEND_CONTAINER` | Frontend container name in its task definition. |

Set the repository variable `AWS_DEPLOY_ENABLED=true` only after all production environment values
are configured.

## AWS Authentication

The deployment workflow uses GitHub OIDC to obtain short-lived AWS credentials. Do not create
long-lived `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` GitHub secrets.

The IAM role trust policy should restrict access to this repository and the `production` GitHub
environment. The role needs only the permissions required to:

- Read and register the configured ECS task-definition families.
- Update and describe the two ECS services.
- Pass the ECS task execution and task roles with `iam:PassRole`.

## Application Secrets

Store runtime secrets in AWS Secrets Manager and reference them from ECS task definitions:

- `OPENAI_API_KEY`
- `JWT_SECRET_KEY`
- `JWT_REFRESH_SECRET_KEY`
- Database credentials or the full `DATABASE_URL`
- Any private GHCR pull credential

GitHub Actions should deploy task definitions without reading or printing these values.

## Database Migrations

Before scaling beyond one backend task, move `alembic upgrade head` out of the backend container
startup command. Run migrations as a dedicated one-off ECS task before updating the backend service
so multiple replicas cannot race to apply the same migration.
