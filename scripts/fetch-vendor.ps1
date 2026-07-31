nuget.exe install -OutputDirectory vendor -PackageSaveMode nuspec -ExcludeVersion Microsoft.Windows.WinMD
nuget.exe install -OutputDirectory vendor -PackageSaveMode nuspec -ExcludeVersion -DependencyVersion Ignore Microsoft.Windows.SDK.Contracts
nuget.exe install -OutputDirectory vendor -PackageSaveMode nuspec -ExcludeVersion -Prerelease Microsoft.Windows.SDK.Win32Metadata
