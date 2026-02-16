"""Tests for public API namespace structure (Story 1.10a)."""


class TestAkgenticNamespace:
    """Verify akgentic top-level exports agent primitives only."""

    def test_agent_primitives_importable(self) -> None:
        from akgentic import (
            Akgent,
            AkgentDeserializeContext,
            ProxyWrapper,
            ActorSystemImpl,
            ExecutionContext,
            ActorProxyWrapper,
            Statistics,
            ActorAddress,
            ActorAddressImpl,
            ActorAddressProxy,
            ActorAddressStopped,
            AgentConfig,
            BaseConfig,
            ReadOnlyField,
            AkgentStateObserver,
            BaseState,
        )
        assert Akgent is not None
        assert AkgentDeserializeContext is not None
        assert ProxyWrapper is not None
        assert ActorSystemImpl is not None
        assert ExecutionContext is not None
        assert ActorProxyWrapper is not None
        assert Statistics is not None
        assert ActorAddress is not None
        assert ActorAddressImpl is not None
        assert ActorAddressProxy is not None
        assert ActorAddressStopped is not None
        assert AgentConfig is not None
        assert BaseConfig is not None
        assert ReadOnlyField is not None
        assert AkgentStateObserver is not None
        assert BaseState is not None

    def test_version_accessible(self) -> None:
        from akgentic import __version__
        assert __version__ == "2.0.0-alpha.1"

    def test_message_types_not_in_all(self) -> None:
        import akgentic
        message_types = {
            "Message", "UserMessage", "ResultMessage", "StopRecursively",
            "StartMessage", "StopMessage", "SentMessage", "ReceivedMessage",
            "ProcessedMessage", "ErrorMessage", "StateChangedMessage",
            "ContextChangedMessage", "ToolUpdateMessage", "date_time_factory",
        }
        assert not message_types.intersection(set(akgentic.__all__))

    def test_serialization_utils_not_in_all(self) -> None:
        import akgentic
        util_symbols = {
            "SerializableBaseModel", "serialize", "serialize_base_model",
            "serialize_type", "get_field_serializers_map", "ActorAddressDict",
            "DeserializeContext", "deserialize_object", "import_class",
            "is_uuid_canonical",
        }
        assert not util_symbols.intersection(set(akgentic.__all__))

    def test_no_duplicate_symbols_in_all(self) -> None:
        import akgentic
        assert len(akgentic.__all__) == len(set(akgentic.__all__))


class TestMessagesNamespace:
    """Verify akgentic.messages exports all message types."""

    def test_all_message_types_importable(self) -> None:
        from akgentic.messages import (
            Message,
            UserMessage,
            ResultMessage,
            StopRecursively,
            date_time_factory,
            ContextChangedMessage,
            ErrorMessage,
            ProcessedMessage,
            ReceivedMessage,
            SentMessage,
            StartMessage,
            StateChangedMessage,
            StopMessage,
            ToolUpdateMessage,
        )
        assert Message is not None
        assert StartMessage is not None

    def test_messages_all_defined(self) -> None:
        import akgentic.messages as msgs
        expected = {
            "Message", "UserMessage", "ResultMessage", "StopRecursively",
            "date_time_factory", "ContextChangedMessage", "ErrorMessage",
            "ProcessedMessage", "ReceivedMessage", "SentMessage", "StartMessage",
            "StateChangedMessage", "StopMessage", "ToolUpdateMessage",
        }
        assert expected.issubset(set(msgs.__all__))


class TestUtilsNamespace:
    """Verify akgentic.utils exports serialization infrastructure."""

    def test_all_utils_importable(self) -> None:
        from akgentic.utils import (
            SerializableBaseModel,
            serialize,
            serialize_base_model,
            serialize_type,
            get_field_serializers_map,
            ActorAddressDict,
            DeserializeContext,
            deserialize_object,
            import_class,
            is_uuid_canonical,
        )
        assert SerializableBaseModel is not None
        assert ActorAddressDict is not None

    def test_utils_all_defined(self) -> None:
        import akgentic.utils as utils
        expected = {
            "SerializableBaseModel", "serialize", "serialize_base_model",
            "serialize_type", "get_field_serializers_map", "ActorAddressDict",
            "DeserializeContext", "deserialize_object", "import_class", "is_uuid_canonical",
        }
        assert expected.issubset(set(utils.__all__))


class TestNoSymbolOverlap:
    """Verify no symbol appears in more than one __all__."""

    def test_no_overlap_between_namespaces(self) -> None:
        import akgentic
        import akgentic.messages
        import akgentic.utils

        top_level = set(akgentic.__all__)
        messages = set(akgentic.messages.__all__)
        utils = set(akgentic.utils.__all__)

        assert not top_level.intersection(messages), (
            f"Overlap between akgentic and akgentic.messages: "
            f"{top_level.intersection(messages)}"
        )
        assert not top_level.intersection(utils), (
            f"Overlap between akgentic and akgentic.utils: "
            f"{top_level.intersection(utils)}"
        )
        assert not messages.intersection(utils), (
            f"Overlap between akgentic.messages and akgentic.utils: "
            f"{messages.intersection(utils)}"
        )
