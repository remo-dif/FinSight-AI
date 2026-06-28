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

The existing task definitions must declare Fargate task-level CPU and memory. Deployments enable
the ECS deployment circuit breaker with automatic rollback and reject task definitions without
resource sizing.

## AWS Environment Configuration

Keep environment-specific resource names and endpoints in the protected GitHub `production`
environment. Do not commit account IDs, ARNs, database endpoints, subnet IDs, or public origins.

| Resource | Configuration source |
| --- | --- |
| ECS cluster | `ECS_CLUSTER` |
| Backend service | `ECS_BACKEND_SERVICE` |
| Frontend service | `ECS_FRONTEND_SERVICE` |
| Backend task family | `ECS_BACKEND_TASK_FAMILY` |
| Frontend task family | `ECS_FRONTEND_TASK_FAMILY` |
| Backend container | `ECS_BACKEND_CONTAINER` |
| Frontend container | `ECS_FRONTEND_CONTAINER` |
| HTTPS ALB origin | `ORIGIN_HTTPS_URL` |
| HTTPS endpoint | `PUBLIC_APP_URL` |
| CloudFront distribution | `CLOUDFRONT_DISTRIBUTION_ID` |
| RDS instance | `RDS_DB_INSTANCE_ID` |
| Upload bucket | `S3_UPLOAD_BUCKET` |

Keep ECS service subnets aligned with the ALB-enabled subnets. If a Fargate task is placed in
an Availability Zone not enabled on the ALB, target health reports `Target.NotInUse` and
deployments can wait indefinitely for stability.

Current listener routing:

| Path | Target group |
| --- | --- |
| `/api/*` | `finsight-ai-backend-tg` |
| `/readyz` | `finsight-ai-backend-tg` |
| default `/` | `finsight-ai-frontend-tg` |

HTTPS is mandatory from the viewer through CloudFront and from CloudFront to the ALB. The deploy
workflow probes both endpoints and inspects the distribution origin policy before changing ECS.

Why this matters for production:

- Traffic is encrypted on both externally reachable hops.
- The deployment gate prevents an edge-only TLS configuration from being released.
- The ALB uses a TLS 1.2+ policy and redirects HTTP to HTTPS.
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
- Set GitHub variable `E2E_TLS_REQUIRED=true`; production deployment rejects every other value.
- Smoke test `https://DOMAIN/readyz` and `https://DOMAIN/`.

Estimated implementation effort: 2-4 hours when the domain is already in Route53, or 0.5-1 day if
domain purchase/delegation and DNS validation are still needed.

## Required Operational Controls

Provision the AWS resources through reviewed infrastructure as code. The production stack should
also include:

- AWS WAF managed core and known-bad-input rule groups plus a rate-based rule for `/api/auth/*`.
- ECS service auto scaling with tested minimum/maximum task counts and CPU or ALB request targets.
- CloudWatch alarms routed through SNS/on-call for ECS running-task shortfall, ALB 5xx/latency,
  RDS CPU/connections/storage, and application error rate.
- S3 versioning, lifecycle/retention policy, public-access block, and encryption.
- Restore drills for RDS and evidence objects, with recorded recovery-time and recovery-point results.

The deployment workflow verifies the release-blocking controls it can inspect safely, but it does
not replace infrastructure provisioning, drift detection, or incident-response testing.

## GHCR Images

After backend tests, frontend tests, Docker builds, and Trivy scans pass on `master`, CI publishes:

- `ghcr.io/remo-dif/finsight-ai-backend:<commit-sha>`
- `ghcr.io/remo-dif/finsight-ai-frontend:<commit-sha>`
Only immutable commit SHA tags are published and deployed. CI does not publish `latest`.

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
| `CLOUDFRONT_DISTRIBUTION_ID` | Distribution checked for WAF and HTTPS-only origins. |
| `RDS_DB_INSTANCE_ID` | Instance checked for Multi-AZ, encryption, and private access. |
| `S3_UPLOAD_BUCKET` | Private encrypted evidence bucket checked before release. |

Set the repository variable `AWS_DEPLOY_ENABLED=true` only after all production environment values
are configured.

Example repository variables (use environment-specific values):

```text
AWS_DEPLOY_ENABLED=true
AWS_ROLE_ARN=<deployment-role-arn>
AWS_REGION=eu-north-1
ECS_CLUSTER=<cluster-name>
ECS_BACKEND_SERVICE=<backend-service-name>
ECS_FRONTEND_SERVICE=<frontend-service-name>
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

The deploy role is supplied through:

```text
AWS_ROLE_ARN=<protected GitHub environment variable>
```

The role needs only the permissions required to:

- Read and register the configured ECS task-definition families.
- Update and describe the two ECS services.
- Run and describe one-off migration tasks for the backend task definition.
- Pass the ECS task execution and task roles with `iam:PassRole`.
- Read CloudFront distribution configuration, describe the RDS instance, and inspect S3 public
  access/encryption configuration for the production release gate.

## Application Secrets

Store runtime secrets in AWS Secrets Manager and reference them from ECS task definitions:

- `OPENAI_API_KEY`
- `JWT_SECRET_KEY`
- `JWT_REFRESH_SECRET_KEY`
- Full `DATABASE_URL`
- Any private GHCR pull credential

GitHub Actions should deploy task definitions without reading or printing these values.

The backend task also requires these non-secret production settings:

```text
APP_ENV=production
STORAGE_BACKEND=s3
S3_UPLOAD_BUCKET=<private bucket name>
S3_UPLOAD_PREFIX=uploads
RATE_LIMIT_BACKEND=redis
REDIS_URL=<ElastiCache endpoint>
```

Its task role needs least-privilege `s3:PutObject` access to the configured upload prefix and
`s3:ListBucket` for readiness checks. Add KMS encrypt permissions when `S3_KMS_KEY_ID` is set.

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

Human CLI access should use IAM Identity Center SSO instead of long-lived root access keys. Configure
an operator-specific profile without committing the SSO start URL or account identifiers:

```powershell
aws configure sso --profile <operator-profile>
aws sso login --profile <operator-profile>
aws sts get-caller-identity --profile <operator-profile>
```

Default workload region:

```text
eu-north-1
```

## Database Migrations

Before scaling beyond one backend task, move `alembic upgrade head` out of the backend container
startup command. Run migrations as a dedicated one-off ECS task before updating the backend service
so multiple replicas cannot race to apply the same migration.
