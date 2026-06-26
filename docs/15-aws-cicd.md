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

## Current AWS Environment

The first AWS environment is deployed in `eu-north-1`:

| Resource | Current value |
| --- | --- |
| ECS cluster | `busy-lion-6wzrd8` |
| Backend service | `finsight-ai-backend-service-cet6tjci` |
| Frontend service | `finsight-ai-frontend-service-0pfkokpq` |
| Backend task family | `finsight-ai-backend` |
| Frontend task family | `finsight-ai-frontend` |
| Backend container | `backend` |
| Frontend container | `frontend` |
| Public ALB | `finsight-ai-alb-19805196.eu-north-1.elb.amazonaws.com` |
| HTTPS endpoint | `https://d3p7l0r823wgar.cloudfront.net` |
| Backend target group | `finsight-ai-backend-tg` |
| Frontend target group | `finsight-ai-frontend-tg` |
| RDS endpoint | `database-1.cv8ik06wq9ev.eu-north-1.rds.amazonaws.com:5432` |

The ALB is enabled in these subnets:

- `subnet-0946545d9d1d70f4f`
- `subnet-0b1e5ecb9ad45873f`

Keep ECS service subnets aligned with the ALB-enabled subnets. If a Fargate task is placed in
an Availability Zone not enabled on the ALB, target health reports `Target.NotInUse` and
deployments can wait indefinitely for stability.

Current listener routing:

| Path | Target group |
| --- | --- |
| `/api/*` | `finsight-ai-backend-tg` |
| `/readyz` | `finsight-ai-backend-tg` |
| default `/` | `finsight-ai-frontend-tg` |

HTTPS is enabled for viewers through CloudFront at
`https://d3p7l0r823wgar.cloudfront.net`. CloudFront redirects HTTP viewers to HTTPS, but the
current origin connection from CloudFront to the ALB is still HTTP. This is edge TLS only, not
full end-to-end TLS.

Why this matters for production:

- Traffic is encrypted between the browser and CloudFront, but not on the CloudFront-to-ALB hop.
- Security reviews will flag this as incomplete TLS termination for a fintech-style application.
- ALB-only controls such as TLS policy enforcement and ALB HTTP-to-HTTPS redirect are not active yet.
- The default `*.elb.amazonaws.com` ALB hostname cannot be used for a public ACM certificate owned by
  this account; use a custom domain instead.

End-to-end TLS between CloudFront and the ALB requires a custom application domain plus an ACM
certificate on the ALB.

Production cutover should block on this HTTPS checklist:

- Request and validate an ACM certificate in `eu-north-1`.
- Add an ALB HTTPS `443` listener using a TLS 1.2+ security policy.
- Move application routing rules to the HTTPS listener.
- Replace the HTTP `80` listener default action with a `301` redirect to HTTPS.
- Update `PUBLIC_APP_URL`, `ALLOWED_ORIGINS`, and any frontend API origin to the HTTPS domain.
- Configure CloudFront with the ALB HTTPS origin and `HTTPS only` origin protocol policy.
- Set GitHub variable `ORIGIN_HTTPS_URL=https://DOMAIN`.
- Set GitHub variable `E2E_TLS_REQUIRED=true` so deployment fails if origin HTTPS regresses.
- Smoke test `https://DOMAIN/readyz` and `https://DOMAIN/`.

Estimated implementation effort: 2-4 hours when the domain is already in Route53, or 0.5-1 day if
domain purchase/delegation and DNS validation are still needed.

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
protection, and configure the remaining variables:

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
| `PUBLIC_APP_URL` | Public HTTPS endpoint used by deploy smoke tests. |
| `ORIGIN_HTTPS_URL` | HTTPS URL for the ALB origin after custom-domain TLS is configured. |
| `E2E_TLS_REQUIRED` | Set to `true` only after ALB origin HTTPS is live; deploys then fail if origin TLS is absent. |

Set the repository variable `AWS_DEPLOY_ENABLED=true` only after all production environment values
are configured.

Current repository variables:

```text
AWS_DEPLOY_ENABLED=true
AWS_ROLE_ARN=arn:aws:iam::649024131408:role/FinSightGitHubActionsDeployRole
AWS_REGION=eu-north-1
ECS_CLUSTER=busy-lion-6wzrd8
ECS_BACKEND_SERVICE=finsight-ai-backend-service-cet6tjci
ECS_FRONTEND_SERVICE=finsight-ai-frontend-service-0pfkokpq
ECS_BACKEND_TASK_FAMILY=finsight-ai-backend
ECS_FRONTEND_TASK_FAMILY=finsight-ai-frontend
ECS_BACKEND_CONTAINER=backend
ECS_FRONTEND_CONTAINER=frontend
```

## AWS Authentication

The deployment workflow uses GitHub OIDC to obtain short-lived AWS credentials. Do not create
long-lived `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` GitHub secrets.

The IAM role trust policy should restrict access to this repository and the `production` GitHub
environment. Because the deploy job uses `environment: production`, the OIDC subject must allow:

```text
repo:remo-dif/FinSight-AI:environment:production
```

The role may also allow the branch subject for direct `master` deploys:

```text
repo:remo-dif/FinSight-AI:ref:refs/heads/master
```

The deploy role is:

```text
arn:aws:iam::649024131408:role/FinSightGitHubActionsDeployRole
```

The role needs only the permissions required to:

- Read and register the configured ECS task-definition families.
- Update and describe the two ECS services.
- Run and describe one-off migration tasks for the backend task definition.
- Pass the ECS task execution and task roles with `iam:PassRole`.

## Application Secrets

Store runtime secrets in AWS Secrets Manager and reference them from ECS task definitions:

- `OPENAI_API_KEY`
- `JWT_SECRET_KEY`
- `JWT_REFRESH_SECRET_KEY`
- Full `DATABASE_URL`
- Any private GHCR pull credential

GitHub Actions should deploy task definitions without reading or printing these values.

The backend task definition currently references these AWS Secrets Manager values:

```text
DATABASE_URL
OPENAI_API_KEY
JWT_SECRET_KEY
JWT_REFRESH_SECRET_KEY
```

When a Secrets Manager secret is stored as key/value JSON, ECS `valueFrom` must include the JSON
key suffix:

```text
arn:aws:secretsmanager:REGION:ACCOUNT:secret:secret-name-random:JSON_KEY::
```

For plaintext secrets, use the plain secret ARN.

## Frontend API Routing

The production frontend defaults to same-origin API requests. This means browser requests use
paths such as:

```text
/api/auth/login
/api/auth/register
```

The ALB forwards `/api/*` to the backend target group. Avoid baking
`NEXT_PUBLIC_API_URL=http://localhost:8000` into the production frontend image; that makes deployed
browsers call their own local machine instead of AWS.

If an explicit public API origin is needed later, set `NEXT_PUBLIC_API_URL` at build time to that
origin. For the current single-ALB setup, leave it unset for production images.

## Local AWS CLI Access

Human CLI access is configured with IAM Identity Center SSO instead of long-lived root access keys.
Use the `finsight-ai` profile:

```powershell
& 'C:\Program Files\Amazon\AWSCLIV2\aws.exe' sso login --profile finsight-ai
& 'C:\Program Files\Amazon\AWSCLIV2\aws.exe' sts get-caller-identity --profile finsight-ai
```

The SSO portal URL is:

```text
https://d-906675e0cc.awsapps.com/start
```

Default workload region:

```text
eu-north-1
```

## Database Migrations

Before scaling beyond one backend task, move `alembic upgrade head` out of the backend container
startup command. Run migrations as a dedicated one-off ECS task before updating the backend service
so multiple replicas cannot race to apply the same migration.
