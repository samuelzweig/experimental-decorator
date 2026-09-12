# experimental-decorator

Python has no standard way to mark a function, class, or method as
provisional. Projects that want to ship something without a stability
guarantee end up hand-rolling their own warning, usually with a `stacklevel`
that points into the library itself instead of the caller who should see it.

`experimental-decorator` gives you a single decorator, `@experimental`, that emits
an `ExperimentalWarning` pointing at the calling code, once per call site,
with metadata other tools can introspect.

## Install

```bash
pip install experimental-decorator
```

No runtime dependencies. Python 3.9+.

## Usage

```python
from experimental_decorator import experimental, is_experimental

@experimental(reason="The return shape may change.", since="0.1.0")
def new_algorithm(data):
    return sorted(data)

new_algorithm([3, 1, 2])
# UserCode.py:1: ExperimentalWarning: function 'new_algorithm' is experimental
# and may change or be removed without notice (since 0.1.0). The return shape
# may change.
#   new_algorithm([3, 1, 2])

is_experimental(new_algorithm)  # True
```

It also works on classes (the warning fires on instantiation, not on class
definition) and on methods:

```python
from experimental_decorator import experimental

@experimental
class Pipeline:
    def __init__(self):
        ...

    @experimental(removal="1.0.0")
    def run_v2(self):
        ...

Pipeline()          # warns: class 'Pipeline' is experimental...
Pipeline().run_v2()  # warns: method 'Pipeline.run_v2' is experimental...
```

Calling the same line in a loop only warns once:

```python
for row in rows:
    new_algorithm(row)  # warns on the first iteration only
```

## Silencing it

The standard library recipe works as-is:

```python
import warnings
from experimental_decorator import ExperimentalWarning

warnings.filterwarnings("ignore", category=ExperimentalWarning)
```

Or scope it to a block with the bundled context manager:

```python
from experimental_decorator import silence_experimental_warnings

with silence_experimental_warnings():
    new_algorithm([3, 1, 2])  # no warning
```

## Introspection

```python
from experimental_decorator import is_experimental, experimental_info

is_experimental(new_algorithm)        # True
experimental_info(new_algorithm)
# ExperimentalInfo(kind='function', qualname='new_algorithm',
#                   reason='The return shape may change.',
#                   since='0.1.0', removal=None)
```

`is_experimental` and `experimental_info` also work on classes, instances,
and bound methods.

## License

MIT
