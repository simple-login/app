from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class UserPlanChange(_message.Message):
    __slots__ = ("plan_end_time",)
    PLAN_END_TIME_FIELD_NUMBER: _ClassVar[int]
    plan_end_time: int
    def __init__(self, plan_end_time: _Optional[int] = ...) -> None: ...

class UserDeleted(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AliasCreated(_message.Message):
    __slots__ = ("alias_id", "alias_email", "alias_note", "enabled")
    ALIAS_ID_FIELD_NUMBER: _ClassVar[int]
    ALIAS_EMAIL_FIELD_NUMBER: _ClassVar[int]
    ALIAS_NOTE_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    alias_id: int
    alias_email: str
    alias_note: str
    enabled: bool
    def __init__(self, alias_id: _Optional[int] = ..., alias_email: _Optional[str] = ..., alias_note: _Optional[str] = ..., enabled: bool = ...) -> None: ...

class AliasStatusChange(_message.Message):
    __slots__ = ("alias_id", "alias_email", "enabled")
    ALIAS_ID_FIELD_NUMBER: _ClassVar[int]
    ALIAS_EMAIL_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    alias_id: int
    alias_email: str
    enabled: bool
    def __init__(self, alias_id: _Optional[int] = ..., alias_email: _Optional[str] = ..., enabled: bool = ...) -> None: ...

class AliasDeleted(_message.Message):
    __slots__ = ("alias_id", "alias_email")
    ALIAS_ID_FIELD_NUMBER: _ClassVar[int]
    ALIAS_EMAIL_FIELD_NUMBER: _ClassVar[int]
    alias_id: int
    alias_email: str
    def __init__(self, alias_id: _Optional[int] = ..., alias_email: _Optional[str] = ...) -> None: ...

class EventContent(_message.Message):
    __slots__ = ("user_plan_change", "user_deleted", "alias_created", "alias_status_change", "alias_deleted")
    USER_PLAN_CHANGE_FIELD_NUMBER: _ClassVar[int]
    USER_DELETED_FIELD_NUMBER: _ClassVar[int]
    ALIAS_CREATED_FIELD_NUMBER: _ClassVar[int]
    ALIAS_STATUS_CHANGE_FIELD_NUMBER: _ClassVar[int]
    ALIAS_DELETED_FIELD_NUMBER: _ClassVar[int]
    user_plan_change: UserPlanChange
    user_deleted: UserDeleted
    alias_created: AliasCreated
    alias_status_change: AliasStatusChange
    alias_deleted: AliasDeleted
    def __init__(self, user_plan_change: _Optional[_Union[UserPlanChange, _Mapping]] = ..., user_deleted: _Optional[_Union[UserDeleted, _Mapping]] = ..., alias_created: _Optional[_Union[AliasCreated, _Mapping]] = ..., alias_status_change: _Optional[_Union[AliasStatusChange, _Mapping]] = ..., alias_deleted: _Optional[_Union[AliasDeleted, _Mapping]] = ...) -> None: ...

class Event(_message.Message):
    __slots__ = ("user_id", "external_user_id", "partner_id", "content")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    EXTERNAL_USER_ID_FIELD_NUMBER: _ClassVar[int]
    PARTNER_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    user_id: int
    external_user_id: str
    partner_id: int
    content: EventContent
    def __init__(self, user_id: _Optional[int] = ..., external_user_id: _Optional[str] = ..., partner_id: _Optional[int] = ..., content: _Optional[_Union[EventContent, _Mapping]] = ...) -> None: ...
