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
flags.h, view.h, index.h, signature.h, schema.h, database.h, cache.h - and
everything they define is imported below, so `winmd.reader.TypeDef` is the
spelling to use whichever module it came from.

They are imported in an order that has no cycle at import time. What is
circular is circular at call time only - a coded index of TypeDefOrRef hands
back a TypeDef row, the row hands back a coded index - and the two places that
cannot be spelled as a plain import say so where they are: index.py takes the
row classes at the end of the file, and the three modules under helpers.py
import it inside the functions that call it.
"""

# the enums, and the tags of each coded index
# a set of files, indexed by namespace
from .cache import (
    cache as cache,
)
from .cache import (
    filter as filter,
)
from .cache import (
    namespace_members as namespace_members,
)

# one file
from .database import (
    Table as Table,
)
from .database import (
    database as database,
)
from .enum import (
    AssemblyFlags as AssemblyFlags,
)
from .enum import (
    AssemblyHashAlgorithm as AssemblyHashAlgorithm,
)
from .enum import (
    CallConv as CallConv,
)
from .enum import (
    CallingConvention as CallingConvention,
)
from .enum import (
    CharSet as CharSet,
)
from .enum import (
    CodeType as CodeType,
)
from .enum import (
    ConstantType as ConstantType,
)
from .enum import (
    CustomAttributeType as CustomAttributeType,
)
from .enum import (
    ElementType as ElementType,
)
from .enum import (
    GenericParamSpecialConstraint as GenericParamSpecialConstraint,
)
from .enum import (
    GenericParamVariance as GenericParamVariance,
)
from .enum import (
    HasConstant as HasConstant,
)
from .enum import (
    HasCustomAttribute as HasCustomAttribute,
)
from .enum import (
    HasDeclSecurity as HasDeclSecurity,
)
from .enum import (
    HasFieldMarshal as HasFieldMarshal,
)
from .enum import (
    HasSemantics as HasSemantics,
)
from .enum import (
    Implementation as Implementation,
)
from .enum import (
    Managed as Managed,
)
from .enum import (
    MemberAccess as MemberAccess,
)
from .enum import (
    MemberForwarded as MemberForwarded,
)
from .enum import (
    MemberRefParent as MemberRefParent,
)
from .enum import (
    MethodDefOrRef as MethodDefOrRef,
)
from .enum import (
    ResolutionScope as ResolutionScope,
)
from .enum import (
    StringFormat as StringFormat,
)
from .enum import (
    TableNumber as TableNumber,
)
from .enum import (
    TypeDefOrRef as TypeDefOrRef,
)
from .enum import (
    TypeLayout as TypeLayout,
)
from .enum import (
    TypeOrMethodDef as TypeOrMethodDef,
)
from .enum import (
    TypeSemantics as TypeSemantics,
)
from .enum import (
    TypeVisibility as TypeVisibility,
)
from .enum import (
    VtableLayout as VtableLayout,
)
from .enum import (
    category as category,
)
from .enum import (
    enum_mask as enum_mask,
)

# one class per column of flags
from .flags import (
    AssemblyAttributes as AssemblyAttributes,
)
from .flags import (
    EventAttributes as EventAttributes,
)
from .flags import (
    FieldAttributes as FieldAttributes,
)
from .flags import (
    GenericParamAttributes as GenericParamAttributes,
)
from .flags import (
    MethodAttributes as MethodAttributes,
)
from .flags import (
    MethodImplAttributes as MethodImplAttributes,
)
from .flags import (
    MethodSemanticsAttributes as MethodSemanticsAttributes,
)
from .flags import (
    ParamAttributes as ParamAttributes,
)
from .flags import (
    PInvokeAttributes as PInvokeAttributes,
)
from .flags import (
    PropertyAttributes as PropertyAttributes,
)
from .flags import (
    TypeAttributes as TypeAttributes,
)

# the free functions
from .helpers import (
    extends_type as extends_type,
)
from .helpers import (
    find as find,
)
from .helpers import (
    find_required as find_required,
)
from .helpers import (
    get_attribute as get_attribute,
)
from .helpers import (
    get_base_class_namespace_and_name as get_base_class_namespace_and_name,
)
from .helpers import (
    get_category as get_category,
)
from .helpers import (
    get_type_namespace_and_name as get_type_namespace_and_name,
)
from .helpers import (
    is_const as is_const,
)
from .helpers import (
    is_nested as is_nested,
)

# a column that may point at one of several tables
from .index import (
    coded_index as coded_index,
)
from .index import (
    coded_index_CustomAttributeType as coded_index_CustomAttributeType,
)
from .index import (
    coded_index_HasConstant as coded_index_HasConstant,
)
from .index import (
    coded_index_HasCustomAttribute as coded_index_HasCustomAttribute,
)
from .index import (
    coded_index_HasDeclSecurity as coded_index_HasDeclSecurity,
)
from .index import (
    coded_index_HasFieldMarshal as coded_index_HasFieldMarshal,
)
from .index import (
    coded_index_HasSemantics as coded_index_HasSemantics,
)
from .index import (
    coded_index_Implementation as coded_index_Implementation,
)
from .index import (
    coded_index_MemberForwarded as coded_index_MemberForwarded,
)
from .index import (
    coded_index_MemberRefParent as coded_index_MemberRefParent,
)
from .index import (
    coded_index_MethodDefOrRef as coded_index_MethodDefOrRef,
)
from .index import (
    coded_index_ResolutionScope as coded_index_ResolutionScope,
)
from .index import (
    coded_index_TypeDefOrRef as coded_index_TypeDefOrRef,
)
from .index import (
    coded_index_TypeOrMethodDef as coded_index_TypeOrMethodDef,
)

# the rows, and the ranges over them
from .schema import (
    Assembly as Assembly,
)
from .schema import (
    AssemblyOS as AssemblyOS,
)
from .schema import (
    AssemblyProcessor as AssemblyProcessor,
)
from .schema import (
    AssemblyRef as AssemblyRef,
)
from .schema import (
    AssemblyRefOS as AssemblyRefOS,
)
from .schema import (
    AssemblyRefProcessor as AssemblyRefProcessor,
)
from .schema import (
    AssemblyVersion as AssemblyVersion,
)
from .schema import (
    ClassLayout as ClassLayout,
)
from .schema import (
    Constant as Constant,
)
from .schema import (
    CustomAttribute as CustomAttribute,
)
from .schema import (
    DeclSecurity as DeclSecurity,
)
from .schema import (
    Event as Event,
)
from .schema import (
    EventMap as EventMap,
)
from .schema import (
    ExportedType as ExportedType,
)
from .schema import (
    Field as Field,
)
from .schema import (
    FieldLayout as FieldLayout,
)
from .schema import (
    FieldMarshal as FieldMarshal,
)
from .schema import (
    FieldRVA as FieldRVA,
)
from .schema import (
    File as File,
)
from .schema import (
    GenericParam as GenericParam,
)
from .schema import (
    GenericParamConstraint as GenericParamConstraint,
)
from .schema import (
    ImplMap as ImplMap,
)
from .schema import (
    InterfaceImpl as InterfaceImpl,
)
from .schema import (
    ManifestResource as ManifestResource,
)
from .schema import (
    MemberRef as MemberRef,
)
from .schema import (
    MethodDef as MethodDef,
)
from .schema import (
    MethodImpl as MethodImpl,
)
from .schema import (
    MethodSemantics as MethodSemantics,
)
from .schema import (
    MethodSpec as MethodSpec,
)
from .schema import (
    Module as Module,
)
from .schema import (
    ModuleRef as ModuleRef,
)
from .schema import (
    NestedClass as NestedClass,
)
from .schema import (
    Param as Param,
)
from .schema import (
    Property as Property,
)
from .schema import (
    PropertyMap as PropertyMap,
)
from .schema import (
    Row as Row,
)
from .schema import (
    RowList as RowList,
)
from .schema import (
    RowRange as RowRange,
)
from .schema import (
    StandAloneSig as StandAloneSig,
)
from .schema import (
    TypeDef as TypeDef,
)
from .schema import (
    TypeRef as TypeRef,
)
from .schema import (
    TypeSpec as TypeSpec,
)
from .schema import (
    make_row as make_row,
)

# the signature blobs and the attribute decoder
from .signature import (
    CustomAttributeSig as CustomAttributeSig,
)
from .signature import (
    CustomModSig as CustomModSig,
)
from .signature import (
    ElemSig as ElemSig,
)
from .signature import (
    EnumDefinition as EnumDefinition,
)
from .signature import (
    EnumValue as EnumValue,
)
from .signature import (
    FieldSig as FieldSig,
)
from .signature import (
    FixedArgSig as FixedArgSig,
)
from .signature import (
    GenericMethodTypeIndex as GenericMethodTypeIndex,
)
from .signature import (
    GenericTypeIndex as GenericTypeIndex,
)
from .signature import (
    GenericTypeInstSig as GenericTypeInstSig,
)
from .signature import (
    MethodDefSig as MethodDefSig,
)
from .signature import (
    NamedArgSig as NamedArgSig,
)
from .signature import (
    ParamSig as ParamSig,
)
from .signature import (
    PropertySig as PropertySig,
)
from .signature import (
    RetTypeSig as RetTypeSig,
)
from .signature import (
    SystemType as SystemType,
)
from .signature import (
    TypeSig as TypeSig,
)
from .signature import (
    TypeSpecSig as TypeSpecSig,
)

# the cursor a blob is read with
from .view import (
    byte_view as byte_view,
)
from .view import (
    uncompress_unsigned as uncompress_unsigned,
)
