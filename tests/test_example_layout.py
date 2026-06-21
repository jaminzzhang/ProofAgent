from pathlib import Path


def test_public_example_directories_are_registered() -> None:
    public_examples = sorted(
        path.name
        for path in Path("examples").iterdir()
        if path.is_dir() and not path.name.startswith("__")
    )

    assert public_examples == [
        "agent_management_insurance_specialist",
        "institution_insurance_specialist",
        "insurance_customer_service",
    ]
