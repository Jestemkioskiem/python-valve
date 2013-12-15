# -*- coding: utf-8 -*-
# Copyright (C) 2013 Oliver Ainsworth

from __future__ import (absolute_import,
                        unicode_literals, print_function, division)

import inspect

from mock import Mock
import pytest

from .. import messages


class TestUseDefault(object):

    def test_pass_value(self):
        instance = messages.MessageField("", optional=False, default_value=5)
        called = []

        @messages.use_default
        def test(instance, value):
            called.append(None)
            assert value == 5

        test(instance, 5)
        assert called

    def test_nonoptional_no_value(self):
        instance = messages.MessageField("", optional=False, default_value=5)
        called = []

        @messages.use_default
        def test(instance, value):
            called.append(None)
            assert value == 5

        with pytest.raises(ValueError):
            test(instance)
        assert not called

    def test_optional_pass_value(self):
        instance = messages.MessageField("", optional=True, default_value=5)
        called = []

        @messages.use_default
        def test(instance, value):
            called.append(None)
            assert value == 10

        test(instance, 10)
        assert called

    def test_optional_no_value(self):
        instance = messages.MessageField("", optional=True, default_value=5)
        called = []

        @messages.use_default
        def test(instance, value):
            called.append(None)
            assert value == 5

        test(instance)
        assert called


class TestNeedsBuffer(object):

    def test_not_empty(self):
        called = []

        @messages.needs_buffer
        def test(instance, buf, values):
            called.append(None)

        test(None, b"...", {})
        assert called

    def test_empty(self):
        called = []

        @messages.needs_buffer
        def test(instance, buf, values):
            called.append(None)

        with pytest.raises(messages.BufferExhaustedError):
            test(None, b"", {})
        assert not called

class TestMessageField(object):

    def test_default_little_endian(self):

        class TestField(messages.MessageField):
            fmt = "i"

        assert TestField("").format.startswith("<")

    def test_explicit_endian(self):
        for fmt in "!<>=@":
            TestField = type(b"TestField",
                             (messages.MessageField,), {"fmt": fmt})
            assert TestField("").format.startswith(fmt)

    def test_validate(self):
        validators = [
            Mock(side_effect=lambda x: x == 5),
            Mock(side_effect=lambda x: isinstance(x, int))
        ]
        field = messages.MessageField("", validators=validators)
        field.validate(5)
        for validator in validators:
            assert validator.called
        with pytest.raises(messages.BrokenMessageError):
            field.validate("10")

    def test_validate_exception(self):
        field = messages.MessageField("", validators=[Mock(side_effect=Exception)])
        with pytest.raises(messages.BrokenMessageError):
            field.validate(5)

    def test_decode_empty(self):
        field = messages.MessageField("")
        with pytest.raises(messages.BufferExhaustedError):
            field.decode(b"")

    def test_decode_small_buffer(self):
        field = messages.MessageField("")
        field.format = b"<d"  # 8 bytes
        with pytest.raises(messages.BufferExhaustedError):
            field.decode(b"\x00\x00\x00\x00\x00\x00\x00")

    def test_decode(self):
        field = messages.MessageField("")
        field.format = b"<B"  # 1 byte
        value, remnants = field.decode(b"\xFF\x01\x02\x03")
        assert value == 255
        assert isinstance(remnants, bytes)
        assert remnants == b"\x01\x02\x03"

    def test_decode_junk(self, monkeypatch):
        field = messages.MessageField("")
        field.format = b"B"
        unpack = Mock(side_effect=messages.struct.error)
        monkeypatch.setattr(messages.struct, "unpack", unpack)
        with pytest.raises(messages.BrokenMessageError):
            field.decode(b"\x01\x02\x03")


class TestStringField(object):

    def test_encode(self):
        field = messages.StringField("")
        encoded = field.encode("Hello")
        assert encoded.endswith(b"\x00")
        assert encoded[:-1] == b"\x48\x65\x6C\x6C\x6F"

    def test_decode(self):
        field = messages.StringField("")
        encoded = b"\x48\x65\x6C\x6C\x6F\x00\x02\x01\x00"
        decoded, remnants = field.decode(encoded)
        assert isinstance(decoded, unicode)
        assert decoded == "Hello"
        assert isinstance(remnants, bytes)
        assert remnants == b"\x02\x01\x00"

    def test_decode_empty(self):
        field = messages.StringField("")
        with pytest.raises(messages.BufferExhaustedError):
            field.decode(b"")

    def test_no_null_terminator(self):
        field = messages.StringField("")
        with pytest.raises(messages.BufferExhaustedError):
            field.decode(b"\xFF\xFF\xFF")


class TestMessageArrayField(object):

    def test_constant_count(self):
        array = messages.MessageArrayField("", None, 5)
        assert array.count() == 5
        assert array.count.minimum == 5

    def test_callable_count(self):
        def function(values={}):
            pass
        array = messages.MessageArrayField("", None, function)
        assert array.count is function

    def test_decode_constant(self):
        class Message(messages.Message):
            fields = messages.ByteField("field"),
        array = messages.MessageArrayField("", Message, 5)
        encoded = b"\x00\x01\x02\x03\x04\x00\x00\x00"
        values, remnants = array.decode(encoded)
        for sub_message, expected in zip(values, range(4)):
            assert sub_message["field"] == expected
        assert isinstance(remnants, bytes)
        assert remnants == b"\x00\x00\x00"

    def test_decode_insufficient_buffer(self):
        class Message(messages.Message):
            fields = messages.ByteField("field"),
        array = messages.MessageArrayField("", Message, 5)
        encoded = b"\xFF\xFE\xFD"
        with pytest.raises(messages.BrokenMessageError):
            array.decode(encoded)

    def test_decode_minimum(self):
        class Message(messages.Message):
            fields = messages.ByteField("field"),
        array = messages.MessageArrayField("", Message, 5)
        array.count.minimum = 2
        encoded = b"\x00\x01"
        values, remnants = array.decode(encoded)  # Minimum
        for sub_message, expected in zip(values, range(1)):
            assert sub_message["field"] == expected
        assert not remnants
        encoded += b"\x02\x03\x04"
        values, remnants = array.decode(encoded)  # Maximum
        for sub_message, expected in zip(values, range(4)):
            assert sub_message["field"] == expected
        assert not remnants

    def test_decode_minimum_remnants(self):
        class Message(messages.Message):
            fields = messages.ShortField("field"),
        array = messages.MessageArrayField("", Message, 3)
        array.count.minimum = 2
        # Two shorts and a trailing byte
        encoded = b"\x00\x00\x11\x11\x22"
        values, remnants = array.decode(encoded)
        for sub_message, expected in zip(values, [0, 0x1111]):
            assert sub_message["field"] == expected
        assert isinstance(remnants, bytes)
        assert remnants == b"\x22"

    def test_count_value_of(self):
        assert messages.MessageArrayField.value_of("f")({"f": 26}) == 26

    def test_count_all(self):
        class Message(messages.Message):
            fields = messages.ByteField(""),
        array = messages.MessageArrayField(
            "", Message, messages.MessageArrayField.all())
        values, remnants = array.decode(b"\x00" * 128)
        assert len(values) == 128
        assert not remnants

    def test_count_all_remnants(self):
        class Message(messages.Message):
            fields = messages.ShortField(""),
        array = messages.MessageArrayField(
            "", Message, messages.MessageArrayField.all())
        values, remnants = array.decode((b"\x00\x00" * 64) + b"\xFF")
        assert len(values) == 64
        assert isinstance(remnants, bytes)
        assert remnants == b"\xFF"

    def test_count_at_least_minimum(self):
        class Message(messages.Message):
            fields = messages.ByteField(""),
        array = messages.MessageArrayField(
            "", Message, messages.MessageArrayField.at_least(5))
        values, remnants = array.decode(b"\x00" * 5)
        assert len(values) == 5
        assert not remnants

    def test_count_at_least_more(self):
        class Message(messages.Message):
            fields = messages.ByteField(""),
        array = messages.MessageArrayField(
            "", Message, messages.MessageArrayField.at_least(5))
        values, remnants = array.decode(b"\x00" * 10)
        assert len(values) == 10
        assert not remnants

    def test_count_at_least_too_few(self):
        class Message(messages.Message):
            fields = messages.ByteField(""),
        array = messages.MessageArrayField(
            "", Message, messages.MessageArrayField.at_least(5))
        with pytest.raises(messages.BrokenMessageError):
            array.decode(b"\x00" * 4)

    def test_count_at_least_remnants(self):
        class Message(messages.Message):
            fields = messages.ShortField(""),
        array = messages.MessageArrayField(
            "", Message, messages.MessageArrayField.at_least(5))
        values, remnants = array.decode((b"\x00\x00" * 10) + b"\xFF")
        assert len(values) == 10
        assert isinstance(remnants, bytes)
        assert remnants == b"\xFF"


class TestMessageDictField(object):

    def test_decode(self):
        ddict = messages.MessageDictField("",
                                          messages.ByteField("key"),
                                          messages.ByteField("value"), 5)
        encoded = b""
        for key in xrange(5):
            encoded += chr(key) + b"\xFF"
        values, remnants = ddict.decode(encoded)
        for key in values.keys():
            assert key in range(5)
            assert values[key] == 255


class TestMessage(object):

    def test_getitem(self):
        assert messages.Message(key=":)")["key"] == ":)"

    def test_setitem(self):
        message = messages.Message()
        message["key"] = ":)"
        assert message["key"] == ":)"

    def test_delitem(self):
        message = messages.Message(key=":(")
        del message["key"]
        with pytest.raises(KeyError):
            message["key"]

    def test_contains(self):
        message = messages.Message(key=":o")
        assert "key" in message

    def test_encode_simple(self):
        class Message(messages.Message):
            fields = (
                messages.ByteField("first_field"),
                messages.ByteField("last_field")
            )
        encoded = Message(first_field=5).encode(last_field=10)
        assert isinstance(encoded, bytes)
        assert encoded == b"\x05\x0A"

    def test_encode_missing_nonoptional_field(self):
        class Message(messages.Message):
            fields = (
                messages.ByteField("first_field"),
                messages.ByteField("last_field")
            )
        with pytest.raises(ValueError):
            Message(first_field=5).encode()

    def test_encode_missing_optional_field(self):
        class Message(messages.Message):
            fields = (
                messages.ByteField("first_field"),
                messages.ByteField("last_field",
                                   optional=True, default_value=10)
            )
        encoded = Message(first_field=5).encode()
        assert isinstance(encoded, bytes)
        assert encoded == b"\x05\x0A"

    # TODO: more complex structures, e.g. ArrayField and DictFields

class TestMSAddressEntry(object):

    def test_decode_ip_insufficient_buffer(self):
        with pytest.raises(messages.BufferExhaustedError):
            messages.MSAddressEntryIPField("").decode(b"\x00\x00")

    def test_decode_ip(self):
        ip, remnants = messages.MSAddressEntryIPField("").decode(
            b"\x00\x01\x02\x03\xFF\xFF")
        assert isinstance(ip, unicode)
        assert ip == "0.1.2.3"
        assert isinstance(remnants, bytes)
        assert remnants == b"\xFF\xFF"

    def test_is_null(self):
        assert messages.MSAddressEntry.decode(
            b"\x00\x00\x00\x00\x00\x00").is_null
        assert not messages.MSAddressEntry.decode(
            b"\x01\x02\x03\x04\x69\x87").is_null
