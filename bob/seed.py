"""Demo account and data, created once when BOB_SEED_DEMO=1."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from bob import fixtures, services
from bob.config import Settings
from bob.models import Investigation, Sample, Study, User

DEMO_EMAIL = "demo@bob.local"
DEMO_PASSWORD = "bob-demo-2026"
DEMO_IRI = "https://example.org/synbiohub/public/bob_demo"


def seed_demo(db: Session, settings: Settings) -> bool:
    if db.scalar(select(User.id).where(User.email == DEMO_EMAIL)):
        return False
    user, ws = services.create_user(db, DEMO_EMAIL, "Demo Scientist", DEMO_PASSWORD)
    ws.name = "Demo Lab"
    ws.slug = services.unique_slug(db, "demo-lab")
    inv = Investigation(
        workspace_id=ws.id,
        title="BOB demo",
        description="Synthetic data shipped with BOB. The IRIs point at example.org placeholders, not real strains.",
        created_by=user.id,
    )
    db.add(inv)
    db.flush()
    study = Study(
        investigation_id=inv.id,
        title="Two-strain consortium characterization",
        description="YFP reporter in a two-strain consortium, one strain alone, untransformed host, and medium blanks.",
    )
    db.add(study)
    db.flush()

    def sample(name: str, sample_type: str, strains: list[tuple[str, str]]) -> Sample:
        s = Sample(study_id=study.id, name=name, sample_type=sample_type)
        db.add(s)
        services.set_sample_components(s, [{"role": "strain", "iri": f"{DEMO_IRI}/{key}/1", "label": label, "sbol_version": "2"} for key, label in strains])
        db.flush()
        return s

    consortium = sample("Consortium X", "sample", [("strain_a", "Strain A (YFP sender)"), ("strain_b", "Strain B (receiver)")])
    strain_y = sample("Strain Y", "sample", [("strain_y", "Strain Y (YFP)")])
    host = sample("Untransformed host", "untransformed", [("host", "Host chassis")])
    medium = sample("Medium only", "medium", [])

    assay = services.import_assay(db, settings, study, "Synthetic plate (demo)", "biotek-gen5-kinetic", "synthetic_gen5.xlsx", fixtures.synthetic_gen5_workbook(), user)
    db.flush()
    layout = {p: consortium for p in fixtures.CONSORTIUM}
    layout |= {p: strain_y for p in fixtures.STRAIN_Y}
    layout |= {p: host for p in fixtures.UNTRANSFORMED}
    layout |= {p: medium for p in fixtures.MEDIUM}
    for well in assay.wells:
        if well.position in layout:
            well.sample_id = layout[well.position].id
    db.commit()
    return True
