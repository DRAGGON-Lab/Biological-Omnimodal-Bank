import datetime as dt
import uuid

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bob.db import Base

ROLES = ("viewer", "editor", "owner")
SAMPLE_TYPES = ("sample", "medium", "untransformed")
COMPONENT_ROLES = ("strain", "plasmid", "inducer", "supplement", "medium", "design", "other")
VISIBILITIES = ("private", "public", "withdrawn")
LICENSES = {"CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/", "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/"}


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _fk(target: str, nullable: bool = False) -> Mapped:
    return mapped_column(String(32), ForeignKey(target, ondelete="CASCADE"), nullable=nullable, index=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    # Stored in each session cookie; bumping it ends every session signed in before the bump.
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _fk("users.id")
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RemoteAccount(Base):
    """A user's sign-in to an outside service such as SynBioHub. The secret is the service's token,
    encrypted with a key derived from BOB's secret key; the user's password for it is never kept."""

    __tablename__ = "remote_accounts"
    __table_args__ = (UniqueConstraint("user_id", "service", "instance"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = _fk("users.id")
    service: Mapped[str] = mapped_column(String(32))
    instance: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(254))
    secret: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="workspace", cascade="all, delete-orphan", passive_deletes=True)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    user_id: Mapped[str] = _fk("users.id")
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship()


class Invitation(Base):
    """An offer of membership that takes effect only when the invitee accepts it.

    Addressed to an email rather than an account, so inviting reveals nothing about which
    emails have accounts; an invitation to an unused email waits for that sign-up.
    """

    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("workspace_id", "email"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    email: Mapped[str] = mapped_column(String(254), index=True)
    role: Mapped[str] = mapped_column(String(16))
    invited_by: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    workspace: Mapped[Workspace] = relationship()
    inviter: Mapped[User | None] = relationship()


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    studies: Mapped[list["Study"]] = relationship(back_populates="investigation", cascade="all, delete-orphan", passive_deletes=True)


class Study(Base):
    __tablename__ = "studies"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = _fk("investigations.id")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    license: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Ordered as they should be cited: [{given_name, family_name, orcid, affiliation}].
    authors: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdraw_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    investigation: Mapped[Investigation] = relationship(back_populates="studies")
    samples: Mapped[list["Sample"]] = relationship(back_populates="study", cascade="all, delete-orphan", passive_deletes=True)
    assays: Mapped[list["Assay"]] = relationship(back_populates="study", cascade="all, delete-orphan", passive_deletes=True)
    versions: Mapped[list["StudyVersion"]] = relationship(back_populates="study", cascade="all, delete-orphan", passive_deletes=True, order_by="StudyVersion.number")
    recipes: Mapped[list["FigureRecipe"]] = relationship(back_populates="study", cascade="all, delete-orphan", passive_deletes=True, order_by="FigureRecipe.id")


class StudyVersion(Base):
    """A published state of a study that readers can always return to and cite.

    The snapshot holds the study's text, samples, and assay layouts; measurements live once per
    assay in FrozenAssay, since they never change after import.
    """

    __tablename__ = "study_versions"
    __table_args__ = (UniqueConstraint("study_id", "number"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    study_id: Mapped[str] = _fk("studies.id")
    number: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(200), default="")
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    study: Mapped[Study] = relationship(back_populates="versions")
    author: Mapped[User | None] = relationship()


class FrozenAssay(Base):
    """An assay's measurements as published. Keyed by the assay id with no foreign key, so it
    outlives the assay when a later version removes it."""

    __tablename__ = "frozen_assays"
    assay_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    study_id: Mapped[str] = _fk("studies.id")
    artifact_id: Mapped[str] = mapped_column(String(32), index=True)
    signals: Mapped[list] = mapped_column(JSON)


class StudyEvent(Base):
    """Who published or withdrew a study, and when."""

    __tablename__ = "study_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    study_id: Mapped[str] = _fk("studies.id")
    kind: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    user: Mapped[User | None] = relationship()


class Sample(Base):
    __tablename__ = "samples"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    study_id: Mapped[str] = _fk("studies.id")
    name: Mapped[str] = mapped_column(String(200))
    sample_type: Mapped[str] = mapped_column(String(16), default="sample")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    study: Mapped[Study] = relationship(back_populates="samples")
    components: Mapped[list["SampleComponent"]] = relationship(
        back_populates="sample", cascade="all, delete-orphan", passive_deletes=True, order_by="SampleComponent.position"
    )


class SampleComponent(Base):
    """A sample's link to something defined elsewhere, such as a strain on SynBioHub.

    The IRI is stored exactly as given and never rewritten, so links stay valid in the store
    that owns them. SBOL version and class are recorded so a later SBOL 3 exporter knows what
    each link points at.
    """

    __tablename__ = "sample_components"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    sample_id: Mapped[str] = _fk("samples.id")
    position: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(16))
    iri: Mapped[str] = mapped_column(String(1000))
    label: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sbol_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    sbol_class: Mapped[str | None] = mapped_column(String(60), nullable=True)

    sample: Mapped[Sample] = relationship(back_populates="components")


class Artifact(Base):
    """An uploaded raw file. Content-addressed and never modified after upload."""

    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = _fk("workspaces.id")
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(120))
    storage_key: Mapped[str] = mapped_column(String(200))
    uploaded_by: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class InstrumentMapping(Base):
    """A versioned `bob-mapping/1` spec. A saved version is never edited; changes add a version."""

    __tablename__ = "instrument_mappings"
    __table_args__ = (UniqueConstraint("workspace_id", "key", "version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(120))
    emoji: Mapped[str | None] = mapped_column(String(8), nullable=True)
    modality: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, default="")
    spec: Mapped[dict] = mapped_column(JSON)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class MappingStar(Base):
    __tablename__ = "mapping_stars"
    __table_args__ = (UniqueConstraint("mapping_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    mapping_id: Mapped[str] = _fk("instrument_mappings.id")
    user_id: Mapped[str] = _fk("users.id")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Assay(Base):
    __tablename__ = "assays"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    study_id: Mapped[str] = _fk("studies.id")
    name: Mapped[str] = mapped_column(String(200))
    modality: Mapped[str] = mapped_column(String(32))
    mapping_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("instrument_mappings.id", ondelete="SET NULL"), nullable=True)
    mapping_key: Mapped[str] = mapped_column(String(64))
    mapping_version: Mapped[int] = mapped_column(Integer)
    artifact_id: Mapped[str] = _fk("artifacts.id")
    run_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    study: Mapped[Study] = relationship(back_populates="assays")
    artifact: Mapped[Artifact] = relationship()
    signals: Mapped[list["Signal"]] = relationship(back_populates="assay", cascade="all, delete-orphan", passive_deletes=True, order_by="Signal.position")
    wells: Mapped[list["Well"]] = relationship(back_populates="assay", cascade="all, delete-orphan", passive_deletes=True)


class Signal(Base):
    """One measured channel of an assay, with the shared time vector for all its series."""

    __tablename__ = "signals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    assay_id: Mapped[str] = _fk("assays.id")
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(24))
    unit: Mapped[str] = mapped_column(String(24))
    description: Mapped[str] = mapped_column(String(200), default="")
    color: Mapped[str] = mapped_column(String(32), default="")
    optics: Mapped[dict] = mapped_column(JSON, default=dict)
    times: Mapped[list] = mapped_column(JSON)

    assay: Mapped[Assay] = relationship(back_populates="signals")
    series: Mapped[list["Series"]] = relationship(back_populates="signal", cascade="all, delete-orphan", passive_deletes=True)


class Series(Base):
    """Observations of one signal at one plate position, aligned to `Signal.times`."""

    __tablename__ = "series"
    __table_args__ = (UniqueConstraint("signal_id", "position"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    signal_id: Mapped[str] = _fk("signals.id")
    position: Mapped[str] = mapped_column(String(8))
    values: Mapped[list] = mapped_column(JSON)

    signal: Mapped[Signal] = relationship(back_populates="series")


class Well(Base):
    """Plate layout: which sample sat at which position during an assay."""

    __tablename__ = "wells"
    __table_args__ = (UniqueConstraint("assay_id", "position"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    assay_id: Mapped[str] = _fk("assays.id")
    position: Mapped[str] = mapped_column(String(8))
    sample_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("samples.id", ondelete="SET NULL"), nullable=True)

    assay: Mapped[Assay] = relationship(back_populates="wells")
    sample: Mapped[Sample | None] = relationship()


class FigureRecipe(Base):
    """A named, study-linked set of plotting selections, reopenable and reusable on another assay."""

    __tablename__ = "figure_recipes"
    __table_args__ = (UniqueConstraint("study_id", "name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    study_id: Mapped[str] = _fk("studies.id")
    assay_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("assays.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    preset: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[dict] = mapped_column(JSON, default=dict)
    layout_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    preview: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    study: Mapped[Study] = relationship(back_populates="recipes")
