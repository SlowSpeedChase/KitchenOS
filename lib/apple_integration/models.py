"""Version-one wire contracts and strict validation for the native bridge."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field as dataclass_field, fields as dataclass_fields
from datetime import date, datetime
import hashlib
import json
import re
from typing import TypedDict
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

class DueFields(TypedDict):
    date: str
    time: str | None
    timezone: str | None


DueValue = DueFields | None
MODEL_VERSION = 1
DOMAINS = frozenset({'shopping', 'prep', 'cooking'})
REMINDER_FIELDS = frozenset({'completed', 'due'})
COOKING_FIELDS = frozenset({'start', 'timezone', 'duration_minutes'})


class InvalidPayload(ValueError):
    """Malformed or unsupported data; do not partially apply it."""


class BatchTooLarge(InvalidPayload):
    """A complete batch cannot fit; never truncate it."""


class RevisionConflict(RuntimeError):
    """The caller's snapshot is no longer current."""


class OwnershipConflict(RuntimeError):
    """The caller or Apple object is not owned by this bridge."""


class SourceUnavailable(RuntimeError):
    """Source missing, stale, or unsafe; never interpret this as an empty set."""


def canonical_json(value) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InvalidPayload('Expected finite JSON values') from exc


def canonical_hash(value) -> str:
    """Content revision, independent of file metadata and dict ordering."""
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise InvalidPayload(f'{name} must be a nonempty string')


def _uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError) as exc:
        raise InvalidPayload('Expected canonical UUID') from exc


def _positive(value, name):
    if type(value) is not int or value < 1:
        raise InvalidPayload(f'{name} must be a positive integer')


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise InvalidPayload('Expected SHA-256 hash')


def validate_scope(domain, week):
    if not isinstance(domain, str) or domain not in DOMAINS:
        raise InvalidPayload('Unknown domain')
    try:
        if not isinstance(week, str) or not re.fullmatch(r'\d{4}-W\d{2}', week):
            raise ValueError()
        date.fromisocalendar(int(week[:4]), int(week[-2:]), 1)
    except ValueError as exc:
        raise InvalidPayload('Expected ISO week key') from exc


def _timezone(value):
    _string(value, 'timezone')
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidPayload('Expected IANA timezone') from exc


def validate_fields(value: dict, domain: str | None = None) -> None:
    """Validate partial field sets too; missing keys do not mean explicit null."""
    if not isinstance(value, dict):
        raise InvalidPayload('fields must be an object')
    allowed = COOKING_FIELDS if domain == 'cooking' else REMINDER_FIELDS if domain else COOKING_FIELDS | REMINDER_FIELDS
    if value.keys() - allowed:
        raise InvalidPayload('Unknown fields')
    canonical_json(value)
    if 'completed' in value and type(value['completed']) is not bool:
        raise InvalidPayload('completed must be boolean')
    if 'due' in value and value['due'] is not None:
        due = value['due']
        if not isinstance(due, dict) or set(due) != {'date', 'time', 'timezone'}:
            raise InvalidPayload('Invalid due value')
        try:
            if not isinstance(due['date'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', due['date']):
                raise ValueError()
            date.fromisoformat(due['date'])
        except ValueError as exc:
            raise InvalidPayload('Invalid due date') from exc
        if due['time'] is None:
            if due['timezone'] is not None:
                raise InvalidPayload('Date-only due has no timezone')
        else:
            if not isinstance(due['time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', due['time']):
                raise InvalidPayload('Invalid due time')
            _timezone(due['timezone'])
    if 'start' in value:
        try:
            if not isinstance(value['start'], str) or 'T' not in value['start']:
                raise ValueError()
            start = datetime.fromisoformat(value['start'])
            if start.tzinfo is None or start.utcoffset() is None:
                raise ValueError()
        except ValueError as exc:
            raise InvalidPayload('start requires an offset-bearing timestamp') from exc
    if 'timezone' in value:
        _timezone(value['timezone'])
    if 'duration_minutes' in value:
        duration = value['duration_minutes']
        if type(duration) is not int or not 15 <= duration <= 360 or duration % 15:
            raise InvalidPayload('duration_minutes must be 15–360 in 15-minute steps')


class Wire:
    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, dict) or payload.keys() - {f.name for f in dataclass_fields(cls)}:
            raise InvalidPayload(f'Unknown {cls.__name__} keys')
        try:
            return cls(**payload)
        except TypeError as exc:
            raise InvalidPayload(f'Invalid {cls.__name__}') from exc

    def to_dict(self):
        return asdict(self)


def _nested(instance, name, cls, optional=False):
    value = getattr(instance, name)
    if optional and value is None:
        return
    if isinstance(value, dict):
        object.__setattr__(instance, name, cls.from_dict(value))
    elif not isinstance(value, cls):
        raise InvalidPayload(f'{name} must be {cls.__name__}')


@dataclass(frozen=True)
class Locator(Wire):
    calendar_id: str
    item_id: str
    external_id: str | None

    def __post_init__(self):
        _string(self.calendar_id, 'calendar_id')
        _string(self.item_id, 'item_id')
        if self.external_id is not None:
            _string(self.external_id, 'external_id')


@dataclass(frozen=True)
class SourceItem(Wire):
    logical_id: str
    domain: str
    week: str
    title: str
    fields: dict
    source_revision: str
    state: str

    def __post_init__(self):
        _string(self.logical_id, 'logical_id')
        _string(self.title, 'title')
        validate_scope(self.domain, self.week)
        validate_fields(self.fields, self.domain)
        _hash(self.source_revision)
        allowed = {'active', 'retired', 'history', 'conflict'}
        if isinstance(self, SyncItem):
            allowed.add('suppressed')
        if not isinstance(self.state, str) or self.state not in allowed:
            raise InvalidPayload('Unknown source state')


@dataclass(frozen=True)
class SyncItem(SourceItem):
    revision: int
    generation: int
    token: str
    destination_id: str
    locator: Locator | None
    common_fields: dict | None

    def __post_init__(self):
        super().__post_init__()
        _positive(self.revision, 'revision')
        _positive(self.generation, 'generation')
        _uuid(self.token)
        _string(self.destination_id, 'destination_id')
        _nested(self, 'locator', Locator, optional=True)
        if self.common_fields is not None:
            validate_fields(self.common_fields, self.domain)


@dataclass(frozen=True)
class BridgeContext(Wire):
    owner_id: str
    owner_generation: int

    def __post_init__(self):
        _uuid(self.owner_id)
        _positive(self.owner_generation, 'owner_generation')


@dataclass(frozen=True)
class Observation(Wire):
    token: str
    generation: int
    revision: int
    availability: str
    locator: Locator | None
    title: str | None
    fields: dict
    absence_confirmed: bool
    issue: str | None
    has_user_notes: bool = False

    def __post_init__(self):
        _uuid(self.token)
        _positive(self.generation, 'generation')
        _positive(self.revision, 'revision')
        _nested(self, 'locator', Locator, optional=True)
        validate_fields(self.fields)
        if self.title is not None:
            _string(self.title, 'title')
        if not isinstance(self.availability, str) or self.availability not in {'present', 'missing', 'unavailable'}:
            raise InvalidPayload('Invalid availability')
        if type(self.absence_confirmed) is not bool or (self.absence_confirmed and self.availability != 'missing'):
            raise InvalidPayload('Only missing observations can confirm absence')
        if self.availability == 'present' and self.locator is None:
            raise InvalidPayload('Present observations require a locator')
        if type(self.has_user_notes) is not bool:
            raise InvalidPayload('has_user_notes must be boolean')
        if self.issue is not None and (not isinstance(self.issue, str) or self.issue not in {'unsupported_all_day', 'unsupported_recurrence', 'identity_ambiguous'}):
            raise InvalidPayload('Unknown observation issue')


def validate_observations(values: list) -> list[Observation]:
    if not isinstance(values, list):
        raise InvalidPayload('observations must be a list')
    observations = [v if isinstance(v, Observation) else Observation.from_dict(v) for v in values]
    if len({v.token for v in observations}) != len(observations):
        raise InvalidPayload('Duplicate observation token')
    return observations


@dataclass(frozen=True)
class AppleOperation(Wire):
    operation_id: str
    token: str
    generation: int
    revision: int
    action: str
    destination_id: str
    locator: Locator | None
    title: str
    fields: dict
    expected_apple_hash: str | None

    def __post_init__(self):
        _uuid(self.operation_id)
        _uuid(self.token)
        _positive(self.generation, 'generation')
        _positive(self.revision, 'revision')
        if not isinstance(self.action, str) or self.action not in {'upsert', 'delete'}:
            raise InvalidPayload('Unknown action')
        _string(self.destination_id, 'destination_id')
        _string(self.title, 'title')
        _nested(self, 'locator', Locator, optional=True)
        validate_fields(self.fields)
        if self.expected_apple_hash is not None:
            _hash(self.expected_apple_hash)


@dataclass(frozen=True)
class ScopeRequest(Wire):
    domain: str
    week: str
    destination_id: str
    state: str
    expected_revision: int

    def __post_init__(self):
        validate_scope(self.domain, self.week)
        _string(self.destination_id, 'destination_id')
        if not isinstance(self.state, str) or self.state not in {'active', 'paused', 'archived'}:
            raise InvalidPayload('Unknown scope state')
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise InvalidPayload('Invalid scope revision')


@dataclass(frozen=True)
class SyncReport(Wire):
    created: int = 0
    updated: int = 0
    deleted: int = 0
    queued: int = 0
    conflicts: int = 0
    unavailable: int = 0
    last_success: str | None = None

    def __post_init__(self):
        for name in ('created', 'updated', 'deleted', 'queued', 'conflicts', 'unavailable'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise InvalidPayload('Report counts must be nonnegative integers')
        if self.last_success is not None:
            validate_fields({'start': self.last_success})


@dataclass(frozen=True)
class WorkBatch(Wire):
    context: BridgeContext
    items: list[SyncItem]
    operations: list[AppleOperation]
    model_version: int = MODEL_VERSION
    scopes: list[dict] = dataclass_field(default_factory=list)
    report: SyncReport = dataclass_field(default_factory=SyncReport)
    paused: bool = False
    retry_requests: list[ObservationRetry] = dataclass_field(default_factory=list)
    retained_items: list[SyncItem] = dataclass_field(default_factory=list)

    def __post_init__(self):
        _nested(self, 'context', BridgeContext)
        _nested(self, 'report', SyncReport)
        if self.model_version != MODEL_VERSION or type(self.paused) is not bool or not isinstance(self.scopes,list) or len(self.scopes)>5000:
            raise InvalidPayload('Invalid work envelope')
        if not isinstance(self.retry_requests,list) or len(self.retry_requests)>1:
            raise InvalidPayload('Invalid retry requests')
        object.__setattr__(self,'retry_requests',[v if isinstance(v,ObservationRetry) else ObservationRetry.from_dict(v) for v in self.retry_requests])
        for name, cls in [('items', SyncItem), ('retained_items', SyncItem), ('operations', AppleOperation)]:
            values = getattr(self, name)
            if not isinstance(values, list) or len(values)>5000:
                raise InvalidPayload(f'{name} must be a bounded list')
            converted = [v if isinstance(v, cls) else cls.from_dict(v) for v in values]
            object.__setattr__(self, name, converted)


@dataclass(frozen=True)
class OperationAck(Wire):
    operation_id: str
    outcome: str
    locator: Locator | None
    observed_fields: dict
    observed_hash: str | None

    def __post_init__(self):
        _uuid(self.operation_id)
        if not isinstance(self.outcome, str) or self.outcome not in {'saved', 'deleted', 'changed', 'failed'}:
            raise InvalidPayload('Unknown acknowledgement outcome')
        _nested(self, 'locator', Locator, optional=True)
        validate_fields(self.observed_fields)
        if self.observed_hash is not None:
            _hash(self.observed_hash)


@dataclass(frozen=True)
class ConflictResolution(Wire):
    conflict_id: str
    choice: str
    expected_revision: int

    def __post_init__(self):
        _uuid(self.conflict_id)
        _string(self.choice, 'choice')
        _positive(self.expected_revision, 'expected_revision')


@dataclass(frozen=True)
class IntegrationStatus(Wire):
    report: SyncReport
    permissions: dict
    destinations: dict
    scopes: list[dict]
    conflicts: list[dict]
    model_version: int = MODEL_VERSION
    configured: bool = False
    connected: bool = False
    paused: bool = False
    settings_revision: int = 0

    def __post_init__(self):
        _nested(self, 'report', SyncReport)
        if self.model_version != MODEL_VERSION or any(type(v) is not bool for v in (self.configured,self.connected,self.paused)) or type(self.settings_revision) is not int or self.settings_revision<0:
            raise InvalidPayload('Invalid status envelope')
        for mapping in (self.permissions, self.destinations):
            if not isinstance(mapping, dict) or mapping.keys() - DOMAINS:
                raise InvalidPayload('Unknown status domain')
        if not isinstance(self.scopes, list) or not isinstance(self.conflicts, list) or len(self.conflicts) > 100:
            raise InvalidPayload('Invalid or unbounded status summary')
        canonical_json(self.to_dict())


@dataclass(frozen=True)
class ObservationRetry(Wire):
    request_id: str
    observations: list[Observation]

    def __post_init__(self):
        _uuid(self.request_id)
        values=validate_observations(self.observations)
        if len(values)>5000:
            raise InvalidPayload('Too many retry observations')
        object.__setattr__(self,'observations',values)


@dataclass(frozen=True)
class OwnedRemovalItem(Wire):
    token: str
    expected_revision: int
    observation: Observation

    def __post_init__(self):
        _uuid(self.token)
        _positive(self.expected_revision,'expected_revision')
        _nested(self,'observation',Observation)
        if self.observation.token!=self.token or self.observation.revision!=self.expected_revision:
            raise InvalidPayload('Removal observation identity/revision mismatch')
        if self.observation.availability!='present' or self.observation.issue is not None:
            raise InvalidPayload('Removal requires verified present ownership')
