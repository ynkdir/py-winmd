"""Tests for the winmd reader.

What the reader answers is checked against the C++ one it was written from, in
test_reference.py; this checks the interface itself - the shapes, the errors and
the corners that are ours rather than the metadata's.

Run with:  python -m unittest discover -s tests   (or python tests/test_winmd.py)
"""

import gc
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import winmd
from winmd.reader import (
    TYPE_DEF,
    AssemblyVersion,
    CallingConvention,
    ConstantType,
    ElementType,
    GenericParamVariance,
    MemberAccess,
    Row,
    TypeAttributes,
    TypeDefOrRef,
    TypeVisibility,
    byte_view,
    cache,
    category,
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
from describe import ROOT, SDK, VENDOR, WIN32      # noqa: E402

FOUNDATION = os.path.join(SDK, "Windows.Foundation.FoundationContract.winmd")
UNIVERSAL = os.path.join(SDK, "Windows.Foundation.UniversalApiContract.winmd")
WIN32_MD = os.path.join(WIN32, "Windows.Win32.winmd")

if not all(os.path.exists(path) for path in (FOUNDATION, UNIVERSAL, WIN32_MD)):
    raise unittest.SkipTest(
        f"no .winmd files under {VENDOR}; run scripts/fetch-vendor.ps1"
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
        self.assertEqual(interface.type(), TypeDefOrRef.TypeSpec)
        generic = interface.TypeSpec().Signature().GenericTypeInst()
        namespace, name = get_type_namespace_and_name(generic.GenericType())
        self.assertEqual((namespace, name), ("Windows.Foundation.Collections", "IIterable`1"))
        self.assertEqual(generic.GenericArgCount(), 1)
        self.assertEqual(generic.ClassOrValueType(), ElementType.Class)

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
        invalid = Row(first.get_database(), TYPE_DEF, -1)
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


class TestModuleLayout(unittest.TestCase):
    def test_reexports(self):
        self.assertIs(winmd.TypeDef, winmd.reader.TypeDef)
        self.assertIs(sys.modules["winmd.reader"], winmd.reader)
        import winmd.reader as reader_module

        self.assertIs(reader_module.cache, cache)

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

