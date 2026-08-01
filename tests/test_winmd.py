"""Tests for the winmd reader.

What the reader answers is checked against the C++ one it was written from, in
test_reference.py; this checks the interface itself - the shapes, the errors and
the corners that are ours rather than the metadata's.

Run with:  python -m unittest discover -s tests   (or python tests/test_winmd.py)
"""

import gc
import glob
import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import winmd
from winmd.reader import (
    AssemblyFlags,
    AssemblyHashAlgorithm,
    AssemblyVersion,
    CallingConvention,
    ConstantType,
    ElementType,
    GenericParamSpecialConstraint,
    GenericParamVariance,
    HasCustomAttribute,
    HasSemantics,
    MemberAccess,
    Row,
    TableNumber,
    TypeAttributes,
    TypeDef,
    TypeDefOrRef,
    TypeLayout,
    TypeVisibility,
    byte_view,
    cache,
    category,
    coded_index,
    database,
    extends_type,
    filter,
    find,
    find_required,
    get_attribute,
    get_base_class_namespace_and_name,
    get_category,
    get_type_namespace_and_name,
    is_nested,
)

# The .winmd files come from the NuGet packages under vendor/, which
# scripts/fetch-vendor.ps1 installs; WINMD_VENDOR points somewhere else.
# They are committed, so their absence is an error rather than a skip.
from describe import ROOT, SDK, VENDOR, WIN32      # noqa: E402

FOUNDATION = os.path.join(SDK, "Windows.Foundation.FoundationContract.winmd")
UNIVERSAL = os.path.join(SDK, "Windows.Foundation.UniversalApiContract.winmd")
WIN32_MD = os.path.join(WIN32, "Windows.Win32.winmd")

_missing = [path for path in (FOUNDATION, UNIVERSAL, WIN32_MD)
            if not os.path.exists(path)]
if _missing:
    raise RuntimeError(
        f"missing metadata under {VENDOR}: " + ", ".join(_missing) + ". It is\n"
        f"committed under vendor/, so this is an incomplete checkout;\n"
        f"scripts/fetch-vendor.ps1 installs it again."
    )


def sdk_files():
    # Windows.WinMD is spelled with a capital MD, which a glob only overlooks
    # where the file system is case sensitive.
    return sorted(
        path for path in glob.glob(os.path.join(SDK, "*"))
        if path.lower().endswith(".winmd")
    )


class TestDatabase(unittest.TestCase):
    def test_is_database(self):
        self.assertTrue(database.is_database(FOUNDATION))
        self.assertFalse(database.is_database(os.path.join(ROOT, "pyproject.toml")))

    def test_open_from_path(self):
        db = database(FOUNDATION)
        self.assertEqual(db.path(), FOUNDATION)
        self.assertGreater(len(db.TypeDef), 0)
        self.assertEqual(len(db.TypeDef), db.TypeDef.size())
        self.assertEqual(db.Module[0].Name(), "Windows.Foundation.FoundationContract.winmd")

    def test_open_from_bytes(self):
        with open(FOUNDATION, "rb") as file:
            db = database(file.read())
        self.assertEqual(db.path(), "")
        self.assertGreater(len(db.TypeDef), 0)

    def test_tables_and_columns(self):
        db = database(FOUNDATION)
        table = db.TypeDef
        self.assertGreater(table.row_size(), 0)
        self.assertGreater(table.column_size(0), 0)
        # TypeDef column 0 is Flags
        self.assertEqual(table.get_value(1, 0), table[1].Flags().value)
        with self.assertRaises(IndexError):
            table.get_value(len(table), 0)
        with self.assertRaises(IndexError):
            table[len(table)]

    def test_iteration_matches_indexing(self):
        db = database(FOUNDATION)
        rows = list(db.TypeDef)
        self.assertEqual(len(rows), len(db.TypeDef))
        self.assertEqual(rows[3], db.TypeDef[3])
        self.assertEqual(rows[-1], db.TypeDef[-1])

    def test_strings_and_blobs(self):
        db = database(FOUNDATION)
        type = db.TypeDef[1]
        self.assertIsInstance(type.TypeName(), str)
        blob = db.get_blob(1)
        self.assertIsInstance(len(blob), int)
        self.assertIsInstance(bytes(blob), bytes)

    def test_no_cache_raises(self):
        db = database(FOUNDATION)
        with self.assertRaises(RuntimeError):
            db.get_cache()


class TestCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = cache(sdk_files())

    def test_databases_and_namespaces(self):
        self.assertEqual(len(self.cache.databases()), len(sdk_files()))
        self.assertIn("Windows.Foundation", self.cache.namespaces())
        members = self.cache.namespaces()["Windows.Foundation"]
        self.assertIn("IAsyncAction", members.types)
        self.assertTrue(any(t.TypeName() == "Uri" for t in members.classes))
        self.assertTrue(any(t.TypeName() == "AsyncStatus" for t in members.enums))
        self.assertTrue(any(t.TypeName() == "Point" for t in members.structs))
        self.assertTrue(any(t.TypeName() == "EventHandler`1" for t in members.delegates))

    def test_namespace_map_interface(self):
        namespaces = self.cache.namespaces()
        self.assertGreater(len(namespaces), 0)
        keys = namespaces.keys()
        self.assertIn("Windows.Foundation", keys)
        self.assertEqual(len(keys), len(namespaces))
        self.assertEqual(len(namespaces.items()), len(namespaces))
        self.assertIsNone(namespaces.get("No.Such.Namespace"))
        with self.assertRaises(KeyError):
            namespaces["No.Such.Namespace"]
        self.assertEqual(sorted(namespaces)[0], sorted(keys)[0])

    def test_find(self):
        found = self.cache.find("Windows.Foundation", "IAsyncAction")
        self.assertTrue(found)
        self.assertEqual(found.TypeName(), "IAsyncAction")
        self.assertEqual(found, self.cache.find("Windows.Foundation.IAsyncAction"))
        self.assertFalse(self.cache.find("Windows.Foundation", "NoSuchType"))
        with self.assertRaises(ValueError):
            self.cache.find_required("Windows.Foundation", "NoSuchType")

    def test_type_filter(self):
        filtered = cache([FOUNDATION], lambda type: type.TypeName().startswith("IAsync"))
        namespaces = filtered.namespaces()
        self.assertIn("Windows.Foundation", namespaces)
        for name in namespaces["Windows.Foundation"].types.keys():
            self.assertTrue(name.startswith("IAsync"))

    def test_add_database(self):
        empty = cache()
        self.assertEqual(len(empty.databases()), 0)
        empty.add_database(FOUNDATION)
        self.assertEqual(len(empty.databases()), 1)
        self.assertTrue(empty.find("Windows.Foundation", "IAsyncAction"))

    def test_remove_type(self):
        local = cache([UNIVERSAL])
        members = local.namespaces()["Windows.Foundation"]
        self.assertTrue(any(t.TypeName() == "Uri" for t in members.classes))
        local.remove_type("Windows.Foundation", "Uri")
        members = local.namespaces()["Windows.Foundation"]
        self.assertFalse(any(t.TypeName() == "Uri" for t in members.classes))

    def test_keeps_owner_alive(self):
        def load():
            return cache([FOUNDATION]).find_required("Windows.Foundation", "IAsyncAction")

        type = load()
        gc.collect()
        self.assertEqual(type.TypeNamespace(), "Windows.Foundation")
        self.assertEqual(type.get_cache().find("Windows.Foundation.IAsyncAction"), type)


class TestTypeDef(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = cache(sdk_files())
        cls.type = cls.cache.find_required("Windows.Foundation", "IAsyncAction")

    def test_flags(self):
        flags = self.type.Flags()
        self.assertEqual(flags.Visibility(), TypeVisibility.Public)
        self.assertTrue(flags.WindowsRuntime())
        self.assertTrue(flags.Abstract())
        self.assertEqual(int(flags), flags.value)
        self.assertEqual(TypeAttributes(flags.value), flags)

    def test_category(self):
        self.assertEqual(get_category(self.type), category.interface_type)
        self.assertEqual(
            get_category(self.cache.find_required("Windows.Foundation.Uri")),
            category.class_type,
        )
        self.assertEqual(
            get_category(self.cache.find_required("Windows.Foundation.Point")),
            category.struct_type,
        )
        self.assertEqual(
            get_category(self.cache.find_required("Windows.Foundation.AsyncStatus")),
            category.enum_type,
        )
        self.assertEqual(
            get_category(self.cache.find_required("Windows.Foundation.EventHandler`1")),
            category.delegate_type,
        )

    def test_methods_and_params(self):
        names = [method.Name() for method in self.type.MethodList()]
        self.assertIn("GetResults", names)
        method = next(m for m in self.type.MethodList() if m.Name() == "put_Completed")
        self.assertTrue(method.Flags().SpecialName())
        self.assertEqual(method.Flags().Access(), MemberAccess.Public)
        self.assertEqual(method.Parent(), self.type)
        signature = method.Signature()
        self.assertEqual(len(signature.Params()), 1)
        self.assertFalse(signature.ReturnType())  # void
        params = [p for p in method.ParamList() if p.Sequence() != 0]
        self.assertEqual([p.Name() for p in params], ["handler"])
        self.assertTrue(params[0].Flags().In())

    def test_ranges(self):
        methods = self.type.MethodList()
        self.assertEqual(len(methods), methods.size())
        self.assertFalse(methods.empty())
        self.assertEqual(methods[0], methods.first)
        self.assertEqual(list(methods)[-1], methods[-1])
        self.assertEqual(methods.second, methods[-1] + 1)
        self.assertEqual(methods[:2], [methods[0], methods[1]])
        # The C++ free functions over a pair are len() and iteration here.
        for name in ("size", "empty", "distance", "begin", "end"):
            self.assertFalse(hasattr(winmd.reader, name))

    def test_enum_definition(self):
        type = self.cache.find_required("Windows.Foundation.AsyncStatus")
        self.assertTrue(type.is_enum())
        definition = type.get_enum_definition()
        self.assertEqual(definition.m_underlying_type, ElementType.I4)
        field = definition.get_enumerator("Completed")
        self.assertEqual(field.Name(), "Completed")
        self.assertEqual(field.Constant().Type(), ConstantType.Int32)
        self.assertEqual(field.Constant().Value(), 1)
        self.assertEqual(field.Constant().ValueInt32(), 1)
        with self.assertRaises(KeyError):
            definition.get_enumerator("NoSuchEnumerator")

    def test_properties_and_events(self):
        type = self.cache.find_required("Windows.Foundation", "Uri")
        properties = [p.Name() for p in type.PropertyList()]
        self.assertIn("Domain", properties)
        property = next(p for p in type.PropertyList() if p.Name() == "Domain")
        self.assertEqual(property.Parent(), type)
        convention = property.Type().CallConvention()
        self.assertEqual(
            winmd.reader.enum_mask(convention, CallingConvention.Mask),
            CallingConvention.Property,
        )
        semantics = list(property.MethodSemantic())
        self.assertTrue(any(s.Semantic().Getter() for s in semantics))
        self.assertTrue(semantics[0].Method().Name().startswith("get_"))

        battery = self.cache.find_required("Windows.Devices.Power", "Battery")
        events = [e.Name() for e in battery.EventList()]
        self.assertIn("ReportUpdated", events)
        event = next(e for e in battery.EventList() if e.Name() == "ReportUpdated")
        self.assertEqual(event.Parent(), battery)
        self.assertTrue(event.EventType())

    def test_generic_params(self):
        type = self.cache.find_required("Windows.Foundation.Collections", "IIterable`1")
        params = list(type.GenericParam())
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0].Name(), "T")
        self.assertEqual(params[0].Number(), 0)
        self.assertEqual(
            params[0].Flags().Variance(),
            GenericParamVariance(params[0].get_value(1) & 0x3),
        )
        self.assertEqual(params[0].Flags().value, params[0].get_value(1))

    def test_interface_impl_and_typespec(self):
        type = self.cache.find_required("Windows.Foundation.Collections", "IVectorView`1")
        impls = list(type.InterfaceImpl())
        self.assertTrue(impls)
        self.assertEqual(impls[0].Class(), type)
        interface = impls[0].Interface()
        self.assertIs(interface.type(), TypeDefOrRef.TypeSpec)
        generic = interface.TypeSpec().Signature().GenericTypeInst()
        namespace, name = get_type_namespace_and_name(generic.GenericType())
        self.assertEqual((namespace, name), ("Windows.Foundation.Collections", "IIterable`1"))
        self.assertEqual(generic.GenericArgCount(), 1)
        self.assertEqual(generic.ClassOrValueType(), ElementType.Class)

    def test_coded_index_kinds_are_classes(self):
        """coded_index<TypeDefOrRef> is a class of its own, as it is in C++."""
        type = self.cache.find_required("Windows.Foundation", "IAsyncAction")
        index = next(iter(type.InterfaceImpl())).Interface()

        self.assertIs(coded_index[TypeDefOrRef], coded_index["TypeDefOrRef"])
        self.assertIsInstance(index, coded_index[TypeDefOrRef])
        self.assertIsInstance(index, coded_index)
        self.assertNotIsInstance(index, coded_index[HasSemantics])
        self.assertEqual(index.kind(), "TypeDefOrRef")
        self.assertIs(index.__class__, coded_index[TypeDefOrRef])

        # Each kind is a class of its own, named after it, with an enum of the
        # tables it can name and a tag width it states itself.
        self.assertEqual(len(winmd.reader._CODED_CLASSES), 13)
        for kind, cls in winmd.reader._CODED_CLASSES.items():
            tables = cls._tables
            enum = getattr(winmd.reader, kind)
            self.assertIs(getattr(winmd.reader, "coded_index_" + kind), cls)
            self.assertIs(coded_index[kind], cls)
            self.assertIs(coded_index[enum], cls)
            self.assertIs(cls._enum, enum)
            self.assertEqual(cls._bits, (len(tables) - 1).bit_length())
            self.assertEqual(cls._mask, (1 << cls._bits) - 1)
            # A member is a tag, named after the table that tag names; the
            # reserved tags of CustomAttributeType name none and are not here.
            self.assertEqual(
                [(member.name, member.value) for member in enum],
                [(table.name, tag) for tag, table in enumerate(tables)
                 if table is not None])

        # The base class holds no kind, so it is not one of them.
        self.assertRaises(TypeError, coded_index, index.get_database(), 1)
        self.assertRaises(KeyError, lambda: coded_index["NotAKind"])

    def test_a_tag_is_compared_with_is(self):
        """Two kinds give the same tag to different tables; `==` cannot tell."""
        type = self.cache.find_required("Windows.Foundation", "IAsyncAction")
        index = next(iter(type.InterfaceImpl())).Interface()

        # type() is the C++ one: this kind's enum, not a table number.
        self.assertIs(index.type(), TypeDefOrRef.TypeRef)
        self.assertIsInstance(index.type(), TypeDefOrRef)
        self.assertIs(index._table(), TableNumber.TypeRef)

        parent = next(iter(type.CustomAttribute())).Parent()
        self.assertIs(parent.type(), HasCustomAttribute.TypeDef)
        self.assertIs(parent._table(), TableNumber.TypeDef)
        # HasCustomAttribute.TypeDef is tag 3 and TypeDefOrRef.TypeDef is tag 0,
        # so this pair is safe either way; MethodDef against TypeDef is not.
        self.assertEqual(HasCustomAttribute.MethodDef, TypeDefOrRef.TypeDef)
        self.assertIsNot(HasCustomAttribute.MethodDef, TypeDefOrRef.TypeDef)

    def test_extends_and_nesting(self):
        type = self.cache.find_required("Windows.Foundation.AsyncStatus")
        self.assertEqual(get_base_class_namespace_and_name(type), ("System", "Enum"))
        self.assertTrue(extends_type(type, "System", "Enum"))
        self.assertFalse(is_nested(type))
        self.assertIsNone(find(type.Extends().TypeRef()))  # System.Enum is not in the cache

    def test_custom_attributes(self):
        type = self.cache.find_required("Windows.Foundation.Collections", "IVector`1")
        names = [".".join(a.TypeNamespaceAndName()) for a in type.CustomAttribute()]
        self.assertIn("Windows.Foundation.Metadata.GuidAttribute", names)
        guid = get_attribute(type, "Windows.Foundation.Metadata", "GuidAttribute")
        self.assertTrue(guid)
        self.assertEqual(guid.Parent().TypeDef(), type)
        values = [arg.value for arg in guid.Value().FixedArgs()]
        self.assertEqual(len(values), 11)  # a GUID: uint32, uint16, uint16, 8 x uint8
        self.assertFalse(get_attribute(type, "No.Such", "Attribute"))

    def test_custom_attribute_named_args(self):
        type = self.cache.find_required("Windows.Foundation", "Uri")
        attribute = get_attribute(
            type, "Windows.Foundation.Metadata", "ActivatableAttribute"
        )
        self.assertTrue(attribute)
        signature = attribute.Value()
        self.assertTrue(signature.FixedArgs())
        for named in signature.NamedArgs():
            self.assertIsInstance(named.name, str)

    def test_row_protocol(self):
        first = self.cache.databases()[0].TypeDef[1]
        second = first + 1
        self.assertEqual(second - first, 1)
        self.assertEqual(second - 1, first)
        self.assertLess(first, second)
        self.assertNotEqual(first, second)
        self.assertEqual({first, first + 0}, {first})
        self.assertTrue(first)

        # A row past the end of its table is not a row, and says so rather than
        # decoding whatever bytes follow.
        invalid = TypeDef(first.get_database(), -1)
        self.assertIsInstance(invalid, Row)
        self.assertFalse(invalid)
        with self.assertRaises(RuntimeError):
            invalid.TypeName()


class TestWin32Metadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = cache(WIN32_MD)

    def test_struct_fields(self):
        type = self.cache.find_required("Windows.Win32.UI.WindowsAndMessaging", "MSG")
        fields = {f.Name(): f for f in type.FieldList()}
        self.assertIn("message", fields)
        self.assertEqual(fields["message"].Signature().Type().Type(), ElementType.U4)
        self.assertEqual(fields["message"].Parent(), type)

    def test_pinvoke_signature(self):
        apis = self.cache.find_required("Windows.Win32.UI.WindowsAndMessaging", "Apis")
        method = next(m for m in apis.MethodList() if m.Name() == "MessageBoxW")
        self.assertTrue(method.Flags().PInvokeImpl())
        signature = method.Signature()
        self.assertEqual(len(signature.Params()), 4)
        self.assertEqual(signature.CallConvention(), CallingConvention.Default)
        namespace, name = get_type_namespace_and_name(
            signature.ReturnType().Type().Type()
        )
        self.assertEqual(name, "MESSAGEBOX_RESULT")

    def test_pointer_types(self):
        apis = self.cache.find_required("Windows.Win32.UI.WindowsAndMessaging", "Apis")
        method = next(m for m in apis.MethodList() if m.Name() == "GetMessageW")
        types = [p.Type() for p in method.Signature().Params()]
        self.assertTrue(any(t.ptr_count() > 0 for t in types))

    def test_nested_types(self):
        found = None
        for name, type in self.cache.namespaces()[
            "Windows.Win32.Networking.WinSock"
        ].types.items():
            if self.cache.nested_types(type):
                found = type
                break
        self.assertIsNotNone(found)
        nested = self.cache.nested_types(found)
        self.assertTrue(all(is_nested(t) for t in nested))
        self.assertEqual(nested[0].EnclosingType(), found)


class TestFilter(unittest.TestCase):
    def test_include_exclude(self):
        rules = filter(["Windows.Foundation"], ["Windows.Foundation.Collections"])
        self.assertFalse(rules.empty())
        self.assertTrue(rules.includes("Windows.Foundation.Uri"))
        self.assertFalse(rules.includes("Windows.Foundation.Collections.IVector`1"))
        self.assertFalse(rules.includes("Windows.Storage.StorageFile"))
        self.assertTrue(filter().empty())
        self.assertTrue(filter().includes("Anything.At.All"))

    def test_includes_typedef(self):
        local = cache([UNIVERSAL])
        rules = filter(["Windows.Foundation.Uri"], [])
        uri = local.find_required("Windows.Foundation.Uri")
        self.assertTrue(rules.includes(uri))
        self.assertTrue(rules.includes([uri]))
        self.assertTrue(rules.includes(local.namespaces()["Windows.Foundation"]))


class TestByteView(unittest.TestCase):
    def test_buffer(self):
        data = bytes([1, 2, 3, 4, 5, 6, 7, 8])
        view = byte_view(data)
        self.assertEqual(len(view), 8)
        self.assertEqual(bytes(view), data)
        self.assertEqual(view[0], 1)
        self.assertEqual(view[-1], 8)
        self.assertEqual(view.as_uint8(1), 2)
        self.assertEqual(view.as_uint16(0), 0x0201)
        self.assertEqual(view.as_uint32(0), 0x04030201)
        self.assertEqual(len(view.seek(4)), 4)
        self.assertEqual(bytes(view.sub(2, 3)), data[2:5])
        self.assertEqual(view.as_bytes(), data)
        with self.assertRaises(ValueError):
            view.sub(0, 9)

    def test_signature_blob(self):
        local = cache([FOUNDATION])
        type = local.find_required("Windows.Foundation", "IAsyncAction")
        method = next(iter(type.MethodList()))
        blob = method.get_database().get_blob(method.get_value(4))
        self.assertGreater(len(blob), 0)
        # A blob knows the database it came out of, so a signature is parsed
        # from the blob alone; the C++ has to be handed the table as well.
        signature = winmd.reader.MethodDefSig(blob)
        self.assertEqual(
            len(signature.Params()), len(method.Signature().Params())
        )


class TestAssembly(unittest.TestCase):
    def test_assembly_row(self):
        db = database(FOUNDATION)
        assembly = db.Assembly[0]
        self.assertEqual(assembly.Name(), "Windows.Foundation.FoundationContract")
        version = assembly.Version()
        self.assertIsInstance(version, AssemblyVersion)
        self.assertEqual(version.MajorVersion, 4)
        self.assertTrue(assembly.Flags().WindowsRuntime())
        self.assertIsInstance(bytes(assembly.PublicKey()), bytes)
        self.assertIs(assembly.HashAlgId(), AssemblyHashAlgorithm.SHA1)
        # AssemblyFlags is the same bits AssemblyAttributes reads one by one.
        self.assertEqual(AssemblyFlags.WindowsRuntime, 0x0200)
        self.assertIn(AssemblyFlags.WindowsRuntime, AssemblyFlags(assembly.Flags().value))

    def test_assembly_ref(self):
        db = database(FOUNDATION)
        names = [ref.Name() for ref in db.AssemblyRef]
        self.assertIn("mscorlib", names)


class TestLifetime(unittest.TestCase):
    """Everything derived from a database must keep the mapped file alive."""

    def test_iterator_outlives_database(self):
        iterator = iter(database(FOUNDATION).TypeDef)
        gc.collect()
        self.assertGreater(len(list(iterator)), 0)

    def test_row_outlives_database(self):
        name = database(FOUNDATION).TypeDef[5].TypeName()
        gc.collect()
        self.assertIsInstance(name, str)

    def test_range_outlives_cache(self):
        def load():
            type = cache([FOUNDATION]).find_required("Windows.Foundation.IAsyncAction")
            return type.MethodList()

        methods = load()
        gc.collect()
        self.assertIn("GetResults", [m.Name() for m in methods])

    def test_signature_outlives_cache(self):
        def load():
            type = cache([FOUNDATION]).find_required("Windows.Foundation.IAsyncAction")
            return next(iter(type.MethodList())).Signature()

        signature = load()
        gc.collect()
        self.assertEqual(len(signature.Params()), 1)

    def test_attribute_value_outlives_cache(self):
        def load():
            type = cache([FOUNDATION]).find_required("Windows.Foundation.IAsyncAction")
            return get_attribute(
                type, "Windows.Foundation.Metadata", "GuidAttribute"
            ).Value()

        signature = load()
        gc.collect()
        self.assertEqual(len(signature.FixedArgs()), 11)

    def test_blob_outlives_database(self):
        blob = database(FOUNDATION).get_blob(1)
        gc.collect()
        self.assertIsInstance(bytes(blob), bytes)

    def test_namespace_members_outlive_cache(self):
        members = cache([FOUNDATION]).namespaces()["Windows.Foundation"]
        gc.collect()
        self.assertGreater(len(members.types), 0)


# What each table's rows can be asked. The C++ has a struct per table holding
# exactly that table's accessors, and so does this; where the two differ the
# comment says why. Moving an accessor to the wrong table fails here.
ROW_ACCESSORS = {
    "Module": "CustomAttribute Generation Name",
    "TypeRef": "CustomAttribute ResolutionScope TypeName TypeNamespace",
    "TypeDef": "CustomAttribute EnclosingType EventList Extends FieldList Flags "
               "GenericParam InterfaceImpl MethodImplList MethodList PropertyList "
               "TypeName TypeNamespace get_enum_definition is_enum",
    "Field": "Constant CustomAttribute FieldMarshal Flags Name Parent Signature",
    "MethodDef": "CustomAttribute Flags GenericParam ImplFlags Name ParamList "
                 "Parent RVA Signature SpecialName",
    "Param": "Constant CustomAttribute FieldMarshal Flags Name Parent Sequence",
    "InterfaceImpl": "Class CustomAttribute Interface",
    "MemberRef": "Class CustomAttribute MethodSignature Name",
    "Constant": "Parent Type Value ValueBoolean ValueInt32 ValueString ValueUInt32",
    "CustomAttribute": "Parent Type TypeNamespaceAndName Value",
    "FieldMarshal": "Parent",
    "DeclSecurity": "",
    "ClassLayout": "ClassSize PackingSize Parent",
    "FieldLayout": "",
    "StandAloneSig": "CustomAttribute Signature",
    "EventMap": "EventList Parent",
    # Event, MethodSemantics and ImplMap spell a column two ways: as the C++
    # names it, and as the name every other table uses.
    "Event": "CustomAttribute EventFlags EventType Flags MethodSemantic Name Parent Type",
    "PropertyMap": "Parent PropertyList",
    "Property": "Constant CustomAttribute Flags MethodSemantic Name Parent Signature Type",
    "MethodSemantics": "Association Flags Method Semantic",
    "MethodImpl": "Class",
    "ModuleRef": "CustomAttribute Name",
    "TypeSpec": "CustomAttribute Signature",
    # The C++ has no accessors for ImplMap at all; these are ours.
    "ImplMap": "Flags ImportName ImportScope MappingFlags MemberForwarded Name",
    "FieldRVA": "",
    "Assembly": "Culture CustomAttribute Flags HashAlgId Name PublicKey Version",
    "AssemblyProcessor": "",
    "AssemblyOS": "",
    "AssemblyRef": "Culture CustomAttribute Flags Name PublicKey Version",
    "AssemblyRefProcessor": "",
    "AssemblyRefOS": "",
    "File": "CustomAttribute Name",
    "ExportedType": "CustomAttribute Flags Name",
    "ManifestResource": "CustomAttribute Flags Name",
    "NestedClass": "EnclosingType NestedType",
    "GenericParam": "CustomAttribute Flags Name Number Owner",
    "MethodSpec": "CustomAttribute",
    "GenericParamConstraint": "CustomAttribute",
}


# What each flags column can be asked. Written out in the reader as the C++
# writes them, so a mask on the wrong accessor fails here.
FLAG_ACCESSORS = {
    "TypeAttributes": "Abstract BeforeFieldInit HasSecurity Import IsTypeForwarder Layout "
                      "RTSpecialName Sealed Semantics Serializable SpecialName "
                      "StringFormat Visibility WindowsRuntime",
    "MethodAttributes": "Abstract Access Final HasSecurity HideBySig Layout PInvokeImpl "
                        "RTSpecialName RequireSecObject SpecialName Static Strict "
                        "UnmanagedExport Virtual",
    "MethodImplAttributes": "CodeType ForwardRef InternalCall Managed NoInlining NoOptimization "
                            "PreserveSig Synchronized",
    "FieldAttributes": "Access HasDefault HasFieldMarshal HasFieldRVA InitOnly Literal "
                       "NotSerialized PInvokeImpl RTSpecialName SpecialName Static",
    "ParamAttributes": "HasDefault HasFieldMarshal In Optional Out",
    "PropertyAttributes": "HasDefault RTSpecialName SpecialName",
    "EventAttributes": "RTSpecialName SpecialName",
    "MethodSemanticsAttributes": "AddOn Fire Getter Other RemoveOn Setter",
    "GenericParamAttributes": "SpecialConstraint Variance",
    "AssemblyAttributes": "DisableJITcompileOptimizer EnableJITcompileTracking PublicKey "
                          "Retargetable WindowsRuntime",
    "PInvokeAttributes": "CallConv CharSet NoMangle SupportsLastError",
}


class TestFlagClasses(unittest.TestCase):
    """One class per flags column, holding that column's fields."""

    def test_accessors_are_where_they_belong(self):
        basics = {name for name in dir(winmd.reader._Flags)
                  if not name.startswith("_")}
        self.assertEqual(basics, {"value"})
        for name, expected in FLAG_ACCESSORS.items():
            cls = getattr(winmd.reader, name)
            own = {n for n in dir(cls) if not n.startswith("_")} - basics
            self.assertEqual(own, set(expected.split()), name)
            self.assertEqual(cls.__slots__, ())

    def test_a_column_does_not_answer_for_another(self):
        self.assertFalse(hasattr(winmd.reader.EventAttributes, "In"))
        self.assertFalse(hasattr(winmd.reader.ParamAttributes, "Static"))

    def test_the_bits_are_read_where_they_are(self):
        """A field of one bit, of several bits, and one that is shifted."""
        flags = TypeAttributes(0x00104101)      # Public, WindowsRuntime, ...
        self.assertEqual(flags.Visibility(), TypeVisibility.Public)
        self.assertTrue(flags.WindowsRuntime())
        self.assertTrue(flags.BeforeFieldInit())
        self.assertFalse(flags.Abstract())
        self.assertEqual(int(flags), 0x00104101)
        self.assertEqual(winmd.reader.MethodAttributes(0x0104).Access(),
                         MemberAccess.Family)

    def test_a_field_keeps_the_bits_it_sits_on(self):
        """The C++ masks the column and does not shift the field down."""
        StringFormat = winmd.reader.StringFormat
        self.assertEqual(TypeAttributes(0x00010000).StringFormat(),
                         StringFormat.UnicodeClass)
        self.assertEqual(int(StringFormat.UnicodeClass), 0x00010000)
        self.assertEqual(int(TypeLayout.ExplicitLayout), 0x00000010)
        self.assertEqual(int(winmd.reader.VtableLayout.NewSlot), 0x0100)
        self.assertEqual(int(winmd.reader.Managed.Unmanaged), 0x0004)
        self.assertEqual(int(winmd.reader.TypeSemantics.Interface), 0x0020)
        # A mask the column cannot hold, which the C++ keeps here too.
        self.assertEqual(int(StringFormat.CustomFormatMask), 0x00C00000)

    def test_which_enums_are_flags(self):
        """The three the README names, and no others: mask, do not compare."""
        import enum

        flags = {name for name in winmd.reader.__all__
                 if isinstance(getattr(winmd.reader, name), type)
                 and issubclass(getattr(winmd.reader, name), enum.IntFlag)}
        self.assertEqual(flags, {"CallingConvention", "AssemblyFlags",
                                 "GenericParamSpecialConstraint"})

    def test_special_constraint_is_a_set_of_bits(self):
        """The C++ masks these three bits without shifting them down."""
        flags = winmd.reader.GenericParamAttributes(0x0014)
        self.assertEqual(flags.SpecialConstraint(),
                         GenericParamSpecialConstraint.ReferenceTypeConstraint
                         | GenericParamSpecialConstraint.DefaultConstructorConstraint)
        self.assertEqual(flags.Variance(), GenericParamVariance.None_)
        # None of them is an empty set, which is false, as it was a false bool.
        none = winmd.reader.GenericParamAttributes(0).SpecialConstraint()
        self.assertFalse(none)
        self.assertEqual(none, GenericParamSpecialConstraint(0))

    def test_the_names_are_the_c_plus_plus_names(self):
        self.assertEqual(MemberAccess.FamAndAssem, 2)
        self.assertEqual(MemberAccess.FamOrAssem, 5)
        self.assertEqual(GenericParamVariance.None_, 0)
        self.assertEqual(TypeVisibility.NestedFamANDAssem, 6)   # this one shouts
        # MethodAttributes calls it Layout, after the column, not the enum.
        self.assertIs(winmd.reader.MethodAttributes(0x0100).Layout(),
                      winmd.reader.VtableLayout.NewSlot)

    def test_a_flags_column_with_no_fields(self):
        """ExportedType and ManifestResource, which the C++ leaves bare too."""
        bare = winmd.reader._Flags(0x1234)
        self.assertEqual(int(bare), 0x1234)
        self.assertEqual(bare, winmd.reader._Flags(0x1234))


class TestRowClasses(unittest.TestCase):
    """One class per table, holding that table's accessors and no others."""

    @classmethod
    def setUpClass(cls):
        cls.db = database(FOUNDATION)

    def _basics(self):
        return {name for name in dir(Row) if not name.startswith("_")}

    def test_a_class_per_table(self):
        self.assertEqual(len(winmd.reader._ROW_CLASSES), 38)
        self.assertEqual(len(TableNumber), 38)
        for table in TableNumber:
            cls = getattr(winmd.reader, table.name)
            self.assertIs(winmd.reader._ROW_CLASSES[table], cls)
            self.assertTrue(issubclass(cls, Row), table.name)
            self.assertIs(cls._table, table, table.name)
            # The table is the class, so a row carries only its own two values.
            self.assertEqual(Row.__slots__, ("_database", "_index", "_columns"))
            self.assertEqual(cls.__slots__, ())

    def test_every_table_is_laid_out(self):
        """_layout gives all 38 their columns, as the C++ constructor does."""
        self.assertFalse(hasattr(winmd.reader, "SCHEMA"))
        self.assertFalse(hasattr(winmd.reader, "TABLE_ORDER"))
        self.assertFalse(hasattr(winmd.reader, "TABLE_NAMES"))
        self.assertEqual(len(self.db._columns), 38)
        for table in TableNumber:
            cls = getattr(winmd.reader, table.name)
            self.assertEqual(table.name, cls.__name__)   # the name is the class
            laid = self.db._columns[table]
            self.assertTrue(laid, table.name)
            # Offsets follow one another, and add up to the row size.
            self.assertEqual([offset for offset, _ in laid],
                             list(itertools.accumulate([0] + [w for _, w in laid[:-1]])),
                             table.name)
            self.assertEqual(self.db._row_size[table],
                             sum(width for _, width in laid), table.name)
            self.assertEqual(len(self.db._format[table]), len(laid) + 1, table.name)

    def test_accessors_are_where_they_belong(self):
        basics = self._basics()
        for name, expected in ROW_ACCESSORS.items():
            cls = getattr(winmd.reader, name)
            own = {n for n in dir(cls) if not n.startswith("_")} - basics
            self.assertEqual(own, set(expected.split()), name)

    def test_a_table_does_not_answer_for_another(self):
        # The flat class this replaced answered Signature() on any row and
        # raised only once it had looked at the table.
        self.assertFalse(hasattr(winmd.reader.TypeDef, "Signature"))
        self.assertFalse(hasattr(winmd.reader.Module, "Flags"))
        self.assertFalse(hasattr(winmd.reader.FieldLayout, "Name"))
        with self.assertRaises(AttributeError):
            self.db.TypeDef[0].Signature()

    def test_every_accessor_runs(self):
        """Call them all: a column number on the wrong table decodes rubbish."""
        basics = self._basics()
        called = 0
        for name in ROW_ACCESSORS:
            table = getattr(self.db, name)
            if not len(table):
                continue
            for row in (table[0], table[-1]):
                for accessor in sorted(set(ROW_ACCESSORS[name].split()) - basics):
                    try:
                        getattr(row, accessor)()
                    except (RuntimeError, ValueError):
                        pass          # no constant, not nested, not in the cache
                    called += 1
        self.assertGreater(called, 100)


class TestModuleLayout(unittest.TestCase):
    def test_all_is_the_module(self):
        """__all__ and what the module offers are the same set."""
        borrowed = {
            "annotations", "bisect", "collections", "dataclass",  # the imports
            "mmap",
            "struct", "Any", "BinaryIO", "Callable", "NamedTuple",
            "Sequence", "TypeVar", "overload",
            "IntEnum", "IntFlag",
            "RowT",                                              # the TypeVar
        }
        # Reachable, but not the spelling to use, so out of __all__: the
        # class of each coded index kind, which is coded_index[kind]; the
        # two ElemSig nests; and make_row, which the row classes do better.
        aside = {"make_row", "SystemType", "EnumValue"} | {
            "coded_index_" + kind for kind in winmd.reader._CODED_CLASSES}

        public = {name for name in vars(winmd.reader)
                  if not name.startswith("_")} - borrowed
        self.assertEqual(public - aside, set(winmd.reader.__all__))
        self.assertEqual(len(winmd.reader.__all__), len(public - aside))  # no repeats
        for name in aside:
            self.assertTrue(hasattr(winmd.reader, name), name)
        # Each of the ones left aside is reached under another name.
        self.assertIs(winmd.reader.ElemSig.SystemType, winmd.reader.SystemType)
        self.assertIs(winmd.reader.ElemSig.EnumValue, winmd.reader.EnumValue)
        self.assertIs(coded_index[TypeDefOrRef],
                      winmd.reader.coded_index_TypeDefOrRef)

        # A star import brings __all__ and nothing the module imported.
        namespace = {}
        exec("from winmd.reader import *", namespace)
        self.assertEqual({n for n in namespace if not n.startswith("__")},
                         set(winmd.reader.__all__))

    def test_the_package_is_the_reader(self):
        """The package is a docstring; winmd.reader is the whole of it."""
        self.assertIs(sys.modules["winmd.reader"], winmd.reader)
        import winmd.reader as reader_module

        self.assertIs(reader_module.cache, cache)
        # One spelling, and importing the module is what binds the name: no
        # winmd.cache beside winmd.reader.cache, and no __all__ listing both.
        self.assertEqual([name for name in vars(winmd) if not name.startswith("_")],
                         ["reader"])
        self.assertFalse(hasattr(winmd, "__all__"))

    def test_all_tables_present(self):
        db = database(FOUNDATION)
        for name in (
            "Module TypeRef TypeDef Field MethodDef Param InterfaceImpl MemberRef Constant "
            "CustomAttribute FieldMarshal DeclSecurity ClassLayout FieldLayout StandAloneSig "
            "EventMap Event PropertyMap Property MethodSemantics MethodImpl ModuleRef TypeSpec "
            "ImplMap FieldRVA Assembly AssemblyProcessor AssemblyOS AssemblyRef "
            "AssemblyRefProcessor AssemblyRefOS File ExportedType ManifestResource NestedClass "
            "GenericParam MethodSpec GenericParamConstraint"
        ).split():
            self.assertTrue(hasattr(db, name), name)
            self.assertTrue(hasattr(winmd.reader, name), name)
            # table<TypeDef> and its pair are one class each here, and nothing
            # hands out a name for them.
            self.assertFalse(hasattr(winmd.reader, name + "_table"), name)
            self.assertFalse(hasattr(winmd.reader, name + "_range"), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)

