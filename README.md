# winmd for Python

[Microsoft.Windows.WinMD](https://github.com/microsoft/winmd) の C++ ヘッダーライブラリ
(`winmd/` 以下) を [nanobind](https://github.com/wjakob/nanobind) でラップした Python 拡張モジュールです。
C++ の `winmd::reader` のインターフェースを、Python の言語仕様で可能な限りそのまま移しています。

```python
import winmd
from winmd.reader import cache, get_category, category

db = cache("metadata/Microsoft.Windows.SDK.Contract/Windows.Foundation.FoundationContract.winmd")
type = db.find_required("Windows.Foundation", "IAsyncAction")

print(type.TypeNamespace(), type.TypeName(), get_category(type))
for method in type.MethodList():
    print(method.Name(), [p.Type().Type() for p in method.Signature().Params()])
```

## ビルド

必要なもの: Windows / Visual Studio (C++ ワークロード) / Python 3.9+。
ビルドは [Meson + meson-python](https://nanobind.readthedocs.io/en/latest/meson.html) で行います。

### 一括セットアップ

```powershell
.\bootstrap.ps1
.\.venv\Scripts\Activate.ps1
python tests\test_winmd.py
```

`bootstrap.ps1` は `.venv` の作成 → ビルド依存 (meson-python / meson / ninja / nanobind) の
インストール → Meson wrap の取得 → MSVC 環境での editable インストール、までを行います。
配布用 wheel を作る場合は `.\bootstrap.ps1 -Wheel` (出力は `dist/`)。

### 手動で行う場合

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install meson-python meson ninja nanobind

# nanobind と robin-map を subprojects/ に取得 (.wrap のみリポジトリに入れる)
meson wrap install robin-map
meson wrap install nanobind

# MSVC 環境で (VS Developer PowerShell か vcvars64.bat を通してから)
pip install --no-build-isolation -e .
```

editable インストールは import 時に ninja で再ビルドするため、**使用時も `.venv` を
有効化**してください (meson / ninja が PATH に必要)。再ビルドを止めたい場合は
`MESONPY_EDITABLE_SKIP` にビルドディレクトリ (`build/cp314`) を設定します。
`vswhere.exe is not recognized` という表示が出る場合は
`%ProgramFiles(x86)%\Microsoft Visual Studio\Installer` を PATH に足すか、
VS Developer PowerShell から実行してください (ビルド自体には影響しません)。

nanobind は Meson の subproject (WrapDB) として静的リンクされるので、
pip の `nanobind` パッケージはスタブ生成にのみ使います。型スタブ
(`python/winmd/**/*.pyi`) は同梱済みで、バインディングを変更したら再生成してください。

```bash
python -m nanobind.stubgen -m winmd._winmd -r -O python/winmd -M python/winmd/py.typed
```

## モジュール構成

| C++ | Python |
| --- | --- |
| `winmd::reader` | `winmd.reader` (`winmd` からも再エクスポート) |
| `winmd::reader::TypeDef` | `winmd.reader.TypeDef` |
| `table<TypeDef>` | `winmd.reader.TypeDef_table` |
| `std::pair<TypeDef, TypeDef>` (範囲) | `winmd.reader.TypeDef_range` |
| `coded_index<TypeDefOrRef>` | `winmd.reader.coded_index_TypeDefOrRef` |
| `cache::namespace_members` | `winmd.reader.cache.namespace_members` |
| `std::list<database>` (`cache::databases()`) | `winmd.reader.database_list` |
| `std::map<std::string_view, namespace_members>` | `winmd.reader.namespace_map` (読み取り専用) |
| `std::map<std::string_view, TypeDef>` | `winmd.reader.type_map` (読み取り専用) |

メソッド名・引数名は C++ のままです (`TypeNamespace()`, `MethodList()`,
`find_required()`, `get_enum_definition()` など)。プロパティ化はしていないので、
C++ と同じく呼び出し形式 `type.TypeName()` になります。

### 型の対応

| C++ | Python |
| --- | --- |
| `std::string_view` / `std::string` | `str` (コピー) |
| `std::u16string_view` (`Constant::ValueString`) | `str` (専用 caster を実装) |
| `char16_t` (`Constant::ValueChar`) | 長さ 1 の `str` (専用 caster を実装) |
| `std::vector<T>` | `list[T]` (コピー) |
| `std::pair<A, B>` | `tuple` |
| `std::optional<T>` / `std::nullptr_t` | `T` または `None` |
| `std::variant<...>` (`TypeSig::Type()`, `Constant::Value()`, `ElemSig::value`) | 対応する Python オブジェクト |
| `enum class` | `enum.IntEnum` (ビット組み合わせを取るものは `enum.IntFlag`) |
| `byte_view` | `winmd.reader.byte_view` (`len()`, `bytes()`, `[]`) |

### 実装済みの範囲

- 38 個すべてのメタデータテーブル行型とそのアクセサ (`schema.h` / `column.h`)
- `coded_index<T>` 13 種、`table<T>`、`table_base`、`database` (全テーブルをメンバとして公開)
- 署名解析一式 — `TypeSig`, `ParamSig`, `RetTypeSig`, `MethodDefSig`, `FieldSig`,
  `PropertySig`, `TypeSpecSig`, `CustomModSig`, `GenericTypeInstSig`, `GenericTypeIndex`,
  `GenericMethodTypeIndex`
- カスタム属性 — `CustomAttributeSig`, `FixedArgSig`, `NamedArgSig`,
  `ElemSig` (`ElemSig.SystemType`, `ElemSig.EnumValue`)、`EnumDefinition`
- `cache` (型フィルタ付きコンストラクタ、`add_database`, `find`, `find_required`,
  `namespaces`, `databases`, `nested_types`, `remove_type`)、`filter`
- フラグ構造体 10 種 (`TypeAttributes` ほか)、`AssemblyVersion`
- 自由関数 — `get_type_namespace_and_name`, `get_base_class_namespace_and_name`,
  `extends_type`, `is_nested`, `find`, `find_required`, `is_const`, `get_attribute`,
  `get_category`, `enum_mask`, `begin`, `end`, `size`, `empty`, `distance`,
  `uncompress_unsigned`, `read_*`, `parse_*`

## Python 化にあたっての差分

- **範囲 (`std::pair<Row, Row>`)** は `Row_range` オブジェクトになります。C++ と同じく
  `.first` / `.second` を持ち、加えて `len()`, `[]`, `for` が使えます。
  `begin(r)`, `end(r)`, `size(r)`, `empty(r)`, `distance(r)` も従来どおり使えます。
- **行はイテレータでもある** ので、`row + 1`, `row - 1`, `row_a - row_b`, 比較演算子、
  `bool(row)`, `hash(row)` が使えます。
- **getter と setter が同名** の `Attributes` 系は、引数の有無で切り替わります
  (`flags.Static()` が getter、`flags.Static(True)` が setter)。
- **`None` という列挙子** は Python の予約語なので `None_` になります
  (`GenericParamVariance.None_`, `AssemblyHashAlgorithm.None_`)。
- **テンプレート引数は名前に埋め込み** ます (`coded_index_TypeDefOrRef`, `Field_table`)。
- **`get_row<Row>()` 相当** は、coded_index に生えている行型名のメソッドです
  (`index.TypeDef()`, `index.MemberRef()` など)。C++ が定義していない coded_index
  (`HasCustomAttribute` など) にも、同じ規則でアクセサを追加してあります。
  種別が一致しない場合、C++ の assert の代わりに例外を投げます。
- **無効な行 (既定構築された `TypeDef()` など) のアクセサ呼び出し** は、C++ では
  未定義動作ですが、ここでは `RuntimeError` になります。`bool(row)` で判定してください。
- **enum は本物の Python enum** です (nanobind の仕様)。列挙子として宣言されていない値を
  返そうとすると `ValueError` になります。ビット組み合わせを取る
  `CallingConvention` / `AssemblyFlags` / `GenericParamSpecialConstraint` は
  `enum.IntFlag` にしてあるので `Property | HasThis` のような合成値も扱えます。
- **`byte_view` はバッファプロトコル非対応** です (nanobind に `def_buffer` 相当がないため)。
  `bytes(view)` / `view.as_bytes()` でコピーを取得してください。
- **寿命管理**: 行・インデックス・署名・`byte_view` は `database` / `cache` が保持する
  メモリマップを参照します。nanobind の `keep_alive` により、そこから辿って得た
  オブジェクトが生きている間は元の `cache` / `database` も生存します
  (`cache` をローカル変数から捨てても安全)。ただし `list` で返る値
  (`Params()`, `FixedArgs()`, `nested_types()` など) と、`TypeSig.Type()` が enum を
  返した場合には寿命の紐付けがないので、C++ と同様に `cache` を保持しておくのが安全です。
- **`namespaces()` / `types`** は読み取り専用のマップビューです (キーが
  メタデータ内の `string_view` を指すため書き換え不可)。`len`, `in`, `[]`,
  `get`, `keys()`, `values()`, `items()`, イテレーションに対応します。

## C++ と同じ「仕様」なので注意する点

- `TypeDef.is_enum()` / `extends_type()` は基底クラス (`Extends()`) を読むため、
  基底のないインターフェースに対して呼ぶと C++ と同じく例外になります。
  先に `if type.Extends():` で確認してください。
- `CustomAttribute.Value()` は引数が enum の場合、その enum 型を `cache` から解決します。
  `mscorlib` などを読み込んでいない場合は
  `Type 'System.Runtime.InteropServices.CallingConvention' could not be found`
  のような `ValueError` になります (C++ の `throw_invalid` と同じ)。
- `read_*` / `uncompress_unsigned` / `parse_*` は渡した `byte_view` を書き換えて
  進めます (C++ の `byte_view&` と同じ)。

## メタデータの取得

`.winmd` はリポジトリに含めていません。テストとサンプルで使うものは NuGet から取得します。

```powershell
.\fetch-metadata.ps1
```

| 取得先ディレクトリ | NuGet パッケージ |
| --- | --- |
| `metadata\Microsoft.Windows.SDK.Contract` | `Microsoft.Windows.SDK.Contracts` (WinRT contracts) |
| `metadata\Microsoft.Windows.SDK.Win32Metadata` | `Microsoft.Windows.SDK.Win32Metadata` (prerelease) |
| `metadata\Microsoft.WindowsAppSDK.WinUI` | `Microsoft.WindowsAppSDK.WinUI` |

`nuget.exe` は PATH のものを使い、無ければ `.tools\nuget.exe` にダウンロードします。
既に取得済みの場合はスキップするので、更新したいときは `-Force` を付けてください。
テストは `WINMD_METADATA` 環境変数で参照先を差し替えられます (未取得の場合はスキップします)。

## サンプル

```bash
# 名前空間の一覧
python examples/dump.py "metadata/Microsoft.Windows.SDK.Contract/*.winmd"

# 型ひとつを C# 風にダンプ
python examples/dump.py --type Windows.Foundation.Uri "metadata/**/*.winmd"

# 名前空間まるごと
python examples/dump.py --namespace Windows.Win32.UI.WindowsAndMessaging "metadata/**/*.winmd"
```

## テスト

```bash
python tests/test_winmd.py
```

`metadata/` 以下の実際の winmd (Windows SDK Contract / Win32Metadata / WinUI) を読んで
45 個のテストを実行します (先に `fetch-metadata.ps1` が必要)。

## ファイル構成

```
meson.build          Meson ビルド定義 (meson-python バックエンド)
subprojects/*.wrap   nanobind / robin-map の取得先 (WrapDB)
bootstrap.ps1        .venv 作成からビルドまでのセットアップスクリプト
fetch-metadata.ps1   テスト用 .winmd を NuGet から取得するスクリプト
winmd/               ラップ対象の C++ ヘッダ (Microsoft.Windows.WinMD)
src/bind.h           共通定義 (テーブル一覧マクロ、範囲ラッパ、keep_alive、独自 caster)
src/module.cpp       モジュール定義
src/enums.cpp        enum.h / flags.h / AssemblyVersion
src/view.cpp         view.h (byte_view, file_view) と blob 読み出しヘルパ
src/rows.cpp         schema.h / column.h の行型 38 種
src/indexes.cpp      coded_index<T> 13 種
src/tables.cpp       table_base / table<T> / 範囲 / database
src/signatures.cpp   signature.h / custom_attribute.h / EnumDefinition
src/cache.cpp        cache.h / filter.h
src/helpers.cpp      type_helpers.h / helpers.h / get_attribute / get_category
python/winmd/        Python パッケージ (拡張モジュールの薄いラッパ + 型スタブ)
```
