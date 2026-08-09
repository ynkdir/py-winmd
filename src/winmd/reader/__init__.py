"""A .winmd reader in nothing but the standard library.

The same ground as the C++ winmd::reader: the PE and CLI headers, the metadata
root and its heaps, the 38 tables with named accessors, the 13 coded indexes,
the signature blobs, the custom attribute decoder, the flag structs and a cache
that indexes types by namespace.

    from winmd.reader import cache, get_category

    db = cache(["Windows.Win32.winmd"])
    type = db.find_required("Windows.Win32.UI.WindowsAndMessaging", "MSG")

    print(type.TypeNamespace(), type.TypeName(), get_category(type))
    for method in type.MethodList():
        print(method.Name(), [p.Type().Type() for p in method.Signature().Params()])

Names and shapes follow the C++ interface, so the two can be compared row for
row; tests/test_reference.py does exactly that. Layout is ECMA-335 partition II
and the table schemas were taken from impl/winmd_reader/database.h.

The modules under here are named after the headers they answer to - enum.h,
flags.h, view.h, table.h, helpers.h, signature.h, schema.h, index.h,
database.h and cache.h - and everything they define is imported below, so
`winmd.reader.TypeDef` is the spelling to use whichever module it came from.

They are imported in an order that has no cycle at import time, and every
import in them is a plain one at the top of its file. What is circular is
circular at call time only - a coded index of TypeDefOrRef hands back a
TypeDef row, the row hands back a coded index - and table.py, which is under
both, reaches the classes built on it through the two registries it holds,
which are full by the time anything calls.
"""

# a set of files, indexed by namespace
from .cache import (
    cache,
    filter,
    namespace_members,
)

# one file
from .database import (
    database,
)

# the enums, and the tags of each coded index
from .enum import (
    AssemblyFlags,
    AssemblyHashAlgorithm,
    CallConv,
    CallingConvention,
    CharSet,
    CodedIndexKind,
    CodeType,
    ConstantType,
    CustomAttributeType,
    ElementType,
    GenericParamSpecialConstraint,
    GenericParamVariance,
    HasConstant,
    HasCustomAttribute,
    HasDeclSecurity,
    HasFieldMarshal,
    HasSemantics,
    Implementation,
    Managed,
    MemberAccess,
    MemberForwarded,
    MemberRefParent,
    MethodDefOrRef,
    ResolutionScope,
    StringFormat,
    TableNumber,
    TypeDefOrRef,
    TypeLayout,
    TypeOrMethodDef,
    TypeSemantics,
    TypeVisibility,
    VtableLayout,
    category,
    enum_mask,
)

# one class per column of flags
from .flags import (
    AssemblyAttributes,
    EventAttributes,
    FieldAttributes,
    GenericParamAttributes,
    MethodAttributes,
    MethodImplAttributes,
    MethodSemanticsAttributes,
    ParamAttributes,
    PInvokeAttributes,
    PropertyAttributes,
    TypeAttributes,
)

# the free functions
from .helpers import (
    carries_attributes,
    extends_type,
    find,
    find_required,
    get_attribute,
    get_base_class_namespace_and_name,
    get_category,
    get_type_namespace_and_name,
    is_const,
    is_nested,
)

# a column that may point at one of several tables
from .index import (
    coded_index_CustomAttributeType,
    coded_index_HasConstant,
    coded_index_HasCustomAttribute,
    coded_index_HasDeclSecurity,
    coded_index_HasFieldMarshal,
    coded_index_HasSemantics,
    coded_index_Implementation,
    coded_index_MemberForwarded,
    coded_index_MemberRefParent,
    coded_index_MethodDefOrRef,
    coded_index_ResolutionScope,
    coded_index_TypeDefOrRef,
    coded_index_TypeOrMethodDef,
)

# the rows, and the ranges over them
from .schema import (
    Assembly,
    AssemblyOS,
    AssemblyProcessor,
    AssemblyRef,
    AssemblyRefOS,
    AssemblyRefProcessor,
    ClassLayout,
    Constant,
    CustomAttribute,
    DeclSecurity,
    Event,
    EventMap,
    ExportedType,
    Field,
    FieldLayout,
    FieldMarshal,
    FieldRVA,
    File,
    GenericParam,
    GenericParamConstraint,
    ImplMap,
    InterfaceImpl,
    ManifestResource,
    MemberRef,
    MethodDef,
    MethodImpl,
    MethodSemantics,
    MethodSpec,
    Module,
    ModuleRef,
    NestedClass,
    Param,
    Property,
    PropertyMap,
    StandAloneSig,
    TypeDef,
    TypeRef,
    TypeSpec,
)

# the signature blobs and the attribute decoder
from .signature import (
    CustomAttributeSig,
    CustomModSig,
    ElemSig,
    EnumDefinition,
    EnumValue,
    FieldSig,
    FixedArgSig,
    GenericMethodTypeIndex,
    GenericTypeIndex,
    GenericTypeInstSig,
    MethodDefSig,
    NamedArgSig,
    ParamSig,
    PropertySig,
    RetTypeSig,
    SystemType,
    TypeSig,
    TypeSpecSig,
)

# what a row, a coded index and a table are made of
from .table import (
    AssemblyVersion,
    Row,
    RowList,
    RowRange,
    Table,
    coded_index,
    make_row,
    table_base,
)

# the cursor a blob is read with
from .view import (
    byte_view,
    uncompress_unsigned,
)

# What winmd.reader offers, which is what the ten modules above define
# and nothing they borrowed. tests/test_winmd.py checks that.
__all__ = [
    "Assembly",
    "AssemblyAttributes",
    "AssemblyFlags",
    "AssemblyHashAlgorithm",
    "AssemblyOS",
    "AssemblyProcessor",
    "AssemblyRef",
    "AssemblyRefOS",
    "AssemblyRefProcessor",
    "AssemblyVersion",
    "CallConv",
    "CallingConvention",
    "CharSet",
    "ClassLayout",
    "CodeType",
    "CodedIndexKind",
    "Constant",
    "ConstantType",
    "CustomAttribute",
    "CustomAttributeSig",
    "CustomAttributeType",
    "CustomModSig",
    "DeclSecurity",
    "ElemSig",
    "ElementType",
    "EnumDefinition",
    "EnumValue",
    "Event",
    "EventAttributes",
    "EventMap",
    "ExportedType",
    "Field",
    "FieldAttributes",
    "FieldLayout",
    "FieldMarshal",
    "FieldRVA",
    "FieldSig",
    "File",
    "FixedArgSig",
    "GenericMethodTypeIndex",
    "GenericParam",
    "GenericParamAttributes",
    "GenericParamConstraint",
    "GenericParamSpecialConstraint",
    "GenericParamVariance",
    "GenericTypeIndex",
    "GenericTypeInstSig",
    "HasConstant",
    "HasCustomAttribute",
    "HasDeclSecurity",
    "HasFieldMarshal",
    "HasSemantics",
    "ImplMap",
    "Implementation",
    "InterfaceImpl",
    "Managed",
    "ManifestResource",
    "MemberAccess",
    "MemberForwarded",
    "MemberRef",
    "MemberRefParent",
    "MethodAttributes",
    "MethodDef",
    "MethodDefOrRef",
    "MethodDefSig",
    "MethodImpl",
    "MethodImplAttributes",
    "MethodSemantics",
    "MethodSemanticsAttributes",
    "MethodSpec",
    "Module",
    "ModuleRef",
    "NamedArgSig",
    "NestedClass",
    "PInvokeAttributes",
    "Param",
    "ParamAttributes",
    "ParamSig",
    "Property",
    "PropertyAttributes",
    "PropertyMap",
    "PropertySig",
    "ResolutionScope",
    "RetTypeSig",
    "Row",
    "RowList",
    "RowRange",
    "StandAloneSig",
    "StringFormat",
    "SystemType",
    "Table",
    "TableNumber",
    "TypeAttributes",
    "TypeDef",
    "TypeDefOrRef",
    "TypeLayout",
    "TypeOrMethodDef",
    "TypeRef",
    "TypeSemantics",
    "TypeSig",
    "TypeSpec",
    "TypeSpecSig",
    "TypeVisibility",
    "VtableLayout",
    "byte_view",
    "cache",
    "carries_attributes",
    "category",
    "coded_index",
    "coded_index_CustomAttributeType",
    "coded_index_HasConstant",
    "coded_index_HasCustomAttribute",
    "coded_index_HasDeclSecurity",
    "coded_index_HasFieldMarshal",
    "coded_index_HasSemantics",
    "coded_index_Implementation",
    "coded_index_MemberForwarded",
    "coded_index_MemberRefParent",
    "coded_index_MethodDefOrRef",
    "coded_index_ResolutionScope",
    "coded_index_TypeDefOrRef",
    "coded_index_TypeOrMethodDef",
    "database",
    "enum_mask",
    "extends_type",
    "filter",
    "find",
    "find_required",
    "get_attribute",
    "get_base_class_namespace_and_name",
    "get_category",
    "get_type_namespace_and_name",
    "is_const",
    "is_nested",
    "make_row",
    "namespace_members",
    "table_base",
    "uncompress_unsigned",
]
