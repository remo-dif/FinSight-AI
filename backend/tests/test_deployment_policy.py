"""Static repository controls, not evidence of an operational cloud account."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_aws_deployment_requires_manual_dispatch_and_explicit_enablement():
    workflow = (ROOT / ".github/workflows/deploy-aws.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "workflow_run:" not in workflow
    assert "  push:" not in workflow and "  pull_request:" not in workflow
    assert "vars.AWS_DEPLOY_ENABLED == 'true'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "environment: production" in workflow
    assert workflow.index("Validate deployment configuration") < workflow.index(
        "Configure AWS credentials"
    )


def test_normal_ci_retains_security_and_quality_gates():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    for gate in (
        "ruff check .",
        "ruff format --check .",
        "pytest",
        "npm run lint",
        "npm run typecheck",
        "npm run build",
        "npm run test:e2e",
        "aquasecurity/trivy-action",
        "actions/dependency-review-action",
    ):
        assert gate in workflow
