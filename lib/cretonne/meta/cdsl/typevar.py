"""
Type variables for Parametric polymorphism.

Cretonne instructions and instruction transformations can be specified to be
polymorphic by using type variables.
"""
from __future__ import absolute_import
import math
from . import types, is_power_of_two

try:
    from typing import Tuple, Union # noqa
    Interval = Tuple[int, int]
    # An Interval where `True` means 'everything'
    BoolInterval = Union[bool, Interval]
except ImportError:
    pass

MAX_LANES = 256
MAX_BITS = 64


def int_log2(x):
    # type: (int) -> int
    return int(math.log(x, 2))


def intersect(a, b):
    # type: (Interval, Interval) -> Interval
    """
    Given two `(min, max)` inclusive intervals, compute their intersection.

    Use `(None, None)` to represent the empty interval on input and output.
    """
    if a[0] is None or b[0] is None:
        return (None, None)
    lo = max(a[0], b[0])
    assert lo is not None
    hi = min(a[1], b[1])
    assert hi is not None
    if lo <= hi:
        return (lo, hi)
    else:
        return (None, None)


def decode_interval(intv, full_range, default=None):
    # type: (BoolInterval, Interval, int) -> Interval
    """
    Decode an interval specification which can take the following values:

    True
        Use the `full_range`.
    `False` or `None`
        An empty interval
    (lo, hi)
        An explicit interval
    """
    if isinstance(intv, tuple):
        # mypy buig here: 'builtins.None' object is not iterable
        lo, hi = intv  # type: ignore
        assert is_power_of_two(lo)
        assert is_power_of_two(hi)
        assert lo <= hi
        assert lo >= full_range[0]
        assert hi <= full_range[1]
        return intv

    if intv:
        return full_range
    else:
        return (default, default)


class TypeSet(object):
    """
    A set of types.

    We don't allow arbitrary subsets of types, but use a parametrized approach
    instead.

    Objects of this class can be used as dictionary keys.

    Parametrized type sets are specified in terms of ranges:

    - The permitted range of vector lanes, where 1 indicates a scalar type.
    - The permitted range of integer types.
    - The permitted range of floating point types, and
    - The permitted range of boolean types.

    The ranges are inclusive from smallest bit-width to largest bit-width.

    A typeset representing scalar integer types `i8` through `i32`:

    >>> TypeSet(ints=(8, 32))
    TypeSet(lanes=(1, 1), ints=(8, 32))

    Passing `True` instead of a range selects all available scalar types:

    >>> TypeSet(ints=True)
    TypeSet(lanes=(1, 1), ints=(8, 64))
    >>> TypeSet(floats=True)
    TypeSet(lanes=(1, 1), floats=(32, 64))
    >>> TypeSet(bools=True)
    TypeSet(lanes=(1, 1), bools=(1, 64))

    Similarly, passing `True` for the lanes selects all possible scalar and
    vector types:

    >>> TypeSet(lanes=True, ints=True)
    TypeSet(lanes=(1, 256), ints=(8, 64))

    :param lanes: `(min, max)` inclusive range of permitted vector lane counts.
    :param ints: `(min, max)` inclusive range of permitted scalar integer
                 widths.
    :param floats: `(min, max)` inclusive range of permitted scalar floating
                   point widths.
    :param bools: `(min, max)` inclusive range of permitted scalar boolean
                  widths.
    """

    def __init__(self, lanes=None, ints=None, floats=None, bools=None):
        # type: (BoolInterval, BoolInterval, BoolInterval, BoolInterval) -> None # noqa
        self.min_lanes, self.max_lanes = decode_interval(
                lanes, (1, MAX_LANES), 1)
        self.min_int, self.max_int = decode_interval(ints, (8, MAX_BITS))
        self.min_float, self.max_float = decode_interval(floats, (32, 64))
        self.min_bool, self.max_bool = decode_interval(bools, (1, MAX_BITS))

    def typeset_key(self):
        # type: () -> Tuple[int, int, int, int, int, int, int, int]
        """Key tuple used for hashing and equality."""
        return (self.min_lanes, self.max_lanes,
                self.min_int, self.max_int,
                self.min_float, self.max_float,
                self.min_bool, self.max_bool)

    def __hash__(self):
        # type: () -> int
        h = hash(self.typeset_key())
        assert h == getattr(self, 'prev_hash', h), "TypeSet changed!"
        self.prev_hash = h
        return h

    def __eq__(self, other):
        return self.typeset_key() == other.typeset_key()

    def __repr__(self):
        # type: () -> str
        s = 'TypeSet(lanes=({}, {})'.format(self.min_lanes, self.max_lanes)
        if self.min_int is not None:
            s += ', ints=({}, {})'.format(self.min_int, self.max_int)
        if self.min_float is not None:
            s += ', floats=({}, {})'.format(self.min_float, self.max_float)
        if self.min_bool is not None:
            s += ', bools=({}, {})'.format(self.min_bool, self.max_bool)
        return s + ')'

    def emit_fields(self, fmt):
        """Emit field initializers for this typeset."""
        fmt.comment(repr(self))
        fields = ('lanes', 'int', 'float', 'bool')
        for field in fields:
            min_val = getattr(self, 'min_' + field)
            max_val = getattr(self, 'max_' + field)
            if min_val is None:
                fmt.line('min_{}: 0,'.format(field))
                fmt.line('max_{}: 0,'.format(field))
            else:
                fmt.line('min_{}: {},'.format(
                    field, int_log2(min_val)))
                fmt.line('max_{}: {},'.format(
                    field, int_log2(max_val) + 1))

    def __iand__(self, other):
        # type: (TypeSet) -> TypeSet
        """
        Intersect self with other type set.

        >>> a = TypeSet(lanes=True, ints=(16, 32))
        >>> a
        TypeSet(lanes=(1, 256), ints=(16, 32))
        >>> b = TypeSet(lanes=(4, 16), ints=True)
        >>> a &= b
        >>> a
        TypeSet(lanes=(4, 16), ints=(16, 32))

        >>> a = TypeSet(lanes=True, bools=(1, 8))
        >>> b = TypeSet(lanes=True, bools=(16, 32))
        >>> a &= b
        >>> a
        TypeSet(lanes=(1, 256))
        """
        self.min_lanes = max(self.min_lanes, other.min_lanes)
        self.max_lanes = min(self.max_lanes, other.max_lanes)

        self.min_int, self.max_int = intersect(
                (self.min_int, self.max_int),
                (other.min_int, other.max_int))

        self.min_float, self.max_float = intersect(
                (self.min_float, self.max_float),
                (other.min_float, other.max_float))

        self.min_bool, self.max_bool = intersect(
                (self.min_bool, self.max_bool),
                (other.min_bool, other.max_bool))

        return self


class TypeVar(object):
    """
    Type variables can be used in place of concrete types when defining
    instructions. This makes the instructions *polymorphic*.

    A type variable is restricted to vary over a subset of the value types.
    This subset is specified by a set of flags that control the permitted base
    types and whether the type variable can assume scalar or vector types, or
    both.

    :param name: Short name of type variable used in instruction descriptions.
    :param doc: Documentation string.
    :param ints: Allow all integer base types, or `(min, max)` bit-range.
    :param floats: Allow all floating point base types, or `(min, max)`
                   bit-range.
    :param bools: Allow all boolean base types, or `(min, max)` bit-range.
    :param scalars: Allow type variable to assume scalar types.
    :param simd: Allow type variable to assume vector types, or `(min, max)`
                 lane count range.
    """

    def __init__(
            self, name, doc,
            ints=False, floats=False, bools=False,
            scalars=True, simd=False,
            base=None, derived_func=None):
        # type: (str, str, BoolInterval, BoolInterval, BoolInterval, bool, BoolInterval, TypeVar, str) -> None # noqa
        self.name = name
        self.__doc__ = doc
        self.singleton_type = None  # type: types.ValueType
        self.is_derived = isinstance(base, TypeVar)
        if base:
            assert self.is_derived
            assert derived_func
            self.base = base
            self.derived_func = derived_func
            self.name = '{}({})'.format(derived_func, base.name)
        else:
            min_lanes = 1 if scalars else 2
            lanes = decode_interval(simd, (min_lanes, MAX_LANES), 1)
            self.type_set = TypeSet(
                    lanes=lanes,
                    ints=ints,
                    floats=floats,
                    bools=bools)

    @staticmethod
    def singleton(typ):
        # type: (types.ValueType) -> TypeVar
        """Create a type variable that can only assume a single type."""
        if isinstance(typ, types.VectorType):
            scalar = typ.base
            lanes = (typ.lanes, typ.lanes)
        elif isinstance(typ, types.ScalarType):
            scalar = typ
            lanes = (1, 1)

        ints = None
        floats = None
        bools = None

        if isinstance(scalar, types.IntType):
            ints = (scalar.bits, scalar.bits)
        elif isinstance(scalar, types.FloatType):
            floats = (scalar.bits, scalar.bits)
        elif isinstance(scalar, types.BoolType):
            bools = (scalar.bits, scalar.bits)

        tv = TypeVar(
                typ.name, 'typeof({})'.format(typ),
                ints, floats, bools, simd=lanes)
        tv.singleton_type = typ
        return tv

    def __str__(self):
        # type: () -> str
        return "`{}`".format(self.name)

    def __repr__(self):
        # type: () -> str
        if self.is_derived:
            return (
                    'TypeVar({}, base={}, derived_func={})'
                    .format(self.name, self.base, self.derived_func))
        else:
            return (
                    'TypeVar({}, {})'
                    .format(self.name, self.type_set))

    def __eq__(self, other):
        if self.is_derived and other.is_derived:
            return (
                    self.derived_func == other.derived_func and
                    self.base == other.base)
        else:
            return self is other

    # Supported functions for derived type variables.
    # The names here must match the method names on `ir::types::Type`.
    # The camel_case of the names must match `enum OperandConstraint` in
    # `instructions.rs`.
    SAMEAS = 'same_as'
    LANEOF = 'lane_of'
    ASBOOL = 'as_bool'
    HALFWIDTH = 'half_width'
    DOUBLEWIDTH = 'double_width'

    @staticmethod
    def derived(base, derived_func):
        # type: (TypeVar, str) -> TypeVar
        """Create a type variable that is a function of another."""
        return TypeVar(None, None, base=base, derived_func=derived_func)

    def change_to_derived(self, base, derived_func):
        # type: (TypeVar, str) -> None
        """Change this type variable into a derived one."""
        self.type_set = None
        self.is_derived = True
        self.base = base
        self.derived_func = derived_func

    def strip_sameas(self):
        # type: () -> TypeVar
        """
        Strip any `SAMEAS` functions from this typevar.

        Also rewrite any `SAMEAS` functions nested under this typevar.
        """
        if self.is_derived:
            self.base = self.base.strip_sameas()
            if self.derived_func == self.SAMEAS:
                return self.base
        return self

    def lane_of(self):
        # type: () -> TypeVar
        """
        Return a derived type variable that is the scalar lane type of this
        type variable.

        When this type variable assumes a scalar type, the derived type will be
        the same scalar type.
        """
        return TypeVar.derived(self, self.LANEOF)

    def as_bool(self):
        # type: () -> TypeVar
        """
        Return a derived type variable that has the same vector geometry as
        this type variable, but with boolean lanes. Scalar types map to `b1`.
        """
        return TypeVar.derived(self, self.ASBOOL)

    def half_width(self):
        # type: () -> TypeVar
        """
        Return a derived type variable that has the same number of vector lanes
        as this one, but the lanes are half the width.
        """
        if not self.is_derived:
            ts = self.type_set
            if ts.min_int:
                assert ts.min_int > 8, "Can't halve all integer types"
            if ts.min_float:
                assert ts.min_float > 32, "Can't halve all float types"
            if ts.min_bool:
                assert ts.min_bool > 8, "Can't halve all boolean types"

        return TypeVar.derived(self, self.HALFWIDTH)

    def double_width(self):
        # type: () -> TypeVar
        """
        Return a derived type variable that has the same number of vector lanes
        as this one, but the lanes are double the width.
        """
        if not self.is_derived:
            ts = self.type_set
            if ts.max_int:
                assert ts.max_int < MAX_BITS, "Can't double all integer types."
            if ts.max_float:
                assert ts.max_float < MAX_BITS, "Can't double all float types."
            if ts.max_bool:
                assert ts.max_bool < MAX_BITS, "Can't double all bool types."

        return TypeVar.derived(self, self.DOUBLEWIDTH)

    def free_typevar(self):
        # type: () -> TypeVar
        """
        Get the free type variable controlling this one.
        """
        if self.is_derived:
            return self.base
        elif self.singleton_type:
            # A singleton type variable is not a proper free variable.
            return None
        else:
            return self

    def rust_expr(self):
        # type: () -> str
        """
        Get a Rust expression that computes the type of this type variable.
        """
        if self.is_derived:
            return '{}.{}()'.format(
                    self.base.rust_expr(), self.derived_func)
        elif self.singleton_type:
            return self.singleton_type.rust_name()
        else:
            return self.name

    def constrain_types(self, other):
        # type: (TypeVar) -> None
        """
        Constrain the range of types this variable can assume to a subset of
        those `other` can assume.

        If this is a SAMEAS-derived type variable, constrain the base instead.
        """
        a = self.strip_sameas()
        b = other.strip_sameas()
        if a is b:
            return

        if not a.is_derived and not b.is_derived:
            a.type_set &= b.type_set
            # TODO: What if a.type_set becomes empty?
            if not a.singleton_type:
                a.singleton_type = b.singleton_type
            return

        # TODO: Implement constraints for derived type variables.
        #
        # If a and b are both derived with the same derived_func, we could say
        # `a.base.constrain_types(b.base)`, but unless the derived_func is
        # injective, that may constrain `a.base` more than necessary.
        #
        # For the fully general case, we would need to compute an image typeset
        # for `b` and propagate a `a.derived_func` pre-image to `a.base`.
