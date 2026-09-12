import warnings

import pytest

from experimental_decorator import (
    ExperimentalInfo,
    ExperimentalWarning,
    experimental,
    experimental_info,
    is_experimental,
    silence_experimental_warnings,
)


# --- functions ---------------------------------------------------------


@experimental
def bare_function(x):
    return x + 1


@experimental(reason="API shape may change.", since="0.1.0", removal="1.0.0")
def documented_function(x):
    return x * 2


def test_bare_function_warns_and_returns_value():
    with pytest.warns(ExperimentalWarning):
        result = bare_function(1)
    assert result == 2


def test_documented_function_message_includes_context():
    with pytest.warns(ExperimentalWarning) as record:
        documented_function(1)
    message = str(record[0].message)
    assert "since 0.1.0" in message
    assert "1.0.0" in message
    assert "API shape may change." in message


def test_function_warning_is_a_future_warning_subclass():
    assert issubclass(ExperimentalWarning, FutureWarning)


# --- classes -------------------------------------------------------------


@experimental
class BareClass:
    def __init__(self, value=0):
        self.value = value


@experimental(reason="Internals may be restructured.")
class DocumentedClass:
    def __init__(self, value=0):
        self.value = value


def test_class_warns_on_instantiation_not_on_definition():
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")

        @experimental
        class DefinedHere:
            def __init__(self):
                pass

        assert record == []  # decorating/defining the class must not warn

        DefinedHere()
        assert len(record) == 1


def test_class_instantiation_warns_and_runs_init():
    with pytest.warns(ExperimentalWarning) as record:
        instance = DocumentedClass(value=5)
    assert instance.value == 5
    assert "Internals may be restructured." in str(record[0].message)


# --- methods ---------------------------------------------------------------


class HasExperimentalMethod:
    @experimental
    def risky(self, x):
        return x - 1


def test_method_warns_on_call():
    obj = HasExperimentalMethod()
    with pytest.warns(ExperimentalWarning):
        result = obj.risky(10)
    assert result == 9


def test_method_warning_message_says_method():
    obj = HasExperimentalMethod()
    with pytest.warns(ExperimentalWarning) as record:
        obj.risky(10)
    assert "method" in str(record[0].message)


# --- stacklevel: warning must point at the caller, not this library --------


def _call_bare_function_here():
    return bare_function(1)  # the line whose number the warning should report


def test_stacklevel_points_at_caller():
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        _call_bare_function_here()
    assert len(record) == 1
    w = record[0]
    assert w.filename == __file__
    # The warning should report the line inside _call_bare_function_here
    # that calls bare_function, not a line inside the library itself.
    source_line = _call_bare_function_here.__code__.co_firstlineno + 1
    assert w.lineno == source_line


def _instantiate_documented_class_here():
    return DocumentedClass()


def test_stacklevel_points_at_caller_for_class():
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        _instantiate_documented_class_here()
    assert len(record) == 1
    assert record[0].filename == __file__


# --- once per call site, not once per call or once globally ---------------


@experimental
def repeatedly_called(x):
    return x


def test_warns_once_per_call_site_not_once_per_call():
    def call_it_in_a_loop():
        results = []
        for _ in range(5):
            results.append(repeatedly_called(1))  # single call site
        return results

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        call_it_in_a_loop()
    assert len(record) == 1


def test_different_call_sites_each_warn_once():
    @experimental
    def another_function(x):
        return x

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        another_function(1)  # call site A
        another_function(1)  # call site B (different line)
    assert len(record) == 2


def test_two_different_decorated_targets_warn_independently():
    @experimental
    def first(x):
        return x

    @experimental
    def second(x):
        return x

    def call_both():
        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always")
            first(1)
            second(1)
        return record

    record = call_both()
    assert len(record) == 2


# --- silencing --------------------------------------------------------


def test_silence_context_manager_suppresses_warning():
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        with silence_experimental_warnings():
            bare_function(1)
        assert record == []


def test_filterwarnings_recipe_suppresses_warning():
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ExperimentalWarning)
        with warnings.catch_warnings(record=True) as record:
            # nested catch_warnings resets filters, so re-apply inside too
            warnings.filterwarnings("ignore", category=ExperimentalWarning)
            bare_function(1)
        assert record == []


def test_silencing_does_not_affect_other_warnings():
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        with silence_experimental_warnings():
            warnings.warn("still visible", UserWarning)
        assert len(record) == 1
        assert record[0].category is UserWarning


# --- introspection ----------------------------------------------------


def test_is_experimental_true_for_marked_function():
    assert is_experimental(bare_function) is True


def test_is_experimental_false_for_plain_function():
    def plain(x):
        return x

    assert is_experimental(plain) is False


def test_is_experimental_true_for_class_and_instance():
    assert is_experimental(BareClass) is True
    with silence_experimental_warnings():
        instance = BareClass()
    assert is_experimental(instance) is True


def test_is_experimental_true_for_bound_method():
    obj = HasExperimentalMethod()
    assert is_experimental(obj.risky) is True


def test_experimental_info_contents():
    info = experimental_info(documented_function)
    assert isinstance(info, ExperimentalInfo)
    assert info.kind == "function"
    assert info.reason == "API shape may change."
    assert info.since == "0.1.0"
    assert info.removal == "1.0.0"


def test_experimental_info_raises_for_unmarked_object():
    def plain(x):
        return x

    with pytest.raises(TypeError):
        experimental_info(plain)


def test_experimental_info_for_class():
    info = experimental_info(DocumentedClass)
    assert info.kind == "class"
    assert info.reason == "Internals may be restructured."

