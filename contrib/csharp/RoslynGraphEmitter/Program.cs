using System.Text.Json;
using Microsoft.Build.Locator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.MSBuild;

static bool IsExcludedPath(string path)
{
    string normalized = path.Replace('\\', '/');
    return normalized.Contains("/bin/", StringComparison.OrdinalIgnoreCase)
        || normalized.Contains("/obj/", StringComparison.OrdinalIgnoreCase)
        || normalized.Contains("/.git/", StringComparison.OrdinalIgnoreCase)
        || normalized.Contains("/.vs/", StringComparison.OrdinalIgnoreCase)
        || normalized.Contains("/packages/", StringComparison.OrdinalIgnoreCase)
        || normalized.Contains("/node_modules/", StringComparison.OrdinalIgnoreCase);
}

static string NormalizePath(string path)
{
    return Path.GetFullPath(path).Replace('\\', '/');
}

static string ResolveRootArg(string[] args)
{
    if (args.Length == 0)
    {
        return Directory.GetCurrentDirectory();
    }

    for (int i = 0; i < args.Length; i++)
    {
        if (string.IsNullOrWhiteSpace(args[i]) || args[i] == "--")
        {
            continue;
        }
        return args[i];
    }

    return Directory.GetCurrentDirectory();
}

var repoRoot = NormalizePath(ResolveRootArg(args));

if (!MSBuildLocator.IsRegistered)
{
    MSBuildLocator.RegisterDefaults();
}

var projectFiles = Directory.EnumerateFiles(repoRoot, "*.csproj", SearchOption.AllDirectories)
    .Where(p => !IsExcludedPath(p))
    .ToList();

if (projectFiles.Count == 0)
{
    Console.WriteLine("{\"edges\":[]}");
    return;
}

using var workspace = MSBuildWorkspace.Create();
workspace.WorkspaceFailed += (_, eventArgs) =>
{
    Console.Error.WriteLine(eventArgs.Diagnostic.ToString());
};

var edges = new HashSet<(string Source, string Target)>(EdgeComparer.OrdinalIgnoreCase);

foreach (string projectPath in projectFiles)
{
    Project? project;
    try
    {
        project = await workspace.OpenProjectAsync(projectPath);
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"Failed to open project '{projectPath}': {ex.Message}");
        continue;
    }

    if (project is null)
    {
        continue;
    }

    foreach (Document document in project.Documents)
    {
        if (string.IsNullOrWhiteSpace(document.FilePath))
        {
            continue;
        }

        string sourcePath = NormalizePath(document.FilePath);
        if (IsExcludedPath(sourcePath))
        {
            continue;
        }

        SyntaxNode? syntaxRoot;
        SemanticModel? semanticModel;
        try
        {
            syntaxRoot = await document.GetSyntaxRootAsync();
            semanticModel = await document.GetSemanticModelAsync();
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Failed to analyze document '{sourcePath}': {ex.Message}");
            continue;
        }

        if (syntaxRoot is null || semanticModel is null)
        {
            continue;
        }

        foreach (IdentifierNameSyntax identifier in syntaxRoot.DescendantNodes().OfType<IdentifierNameSyntax>())
        {
            ISymbol? symbol = semanticModel.GetSymbolInfo(identifier).Symbol;
            symbol ??= semanticModel.GetTypeInfo(identifier).Type;
            if (symbol is null)
            {
                continue;
            }

            Location? targetLocation = symbol.Locations
                .FirstOrDefault(l => l.IsInSource && l.SourceTree?.FilePath is not null);
            if (targetLocation?.SourceTree?.FilePath is not string rawTargetPath)
            {
                continue;
            }

            string targetPath = NormalizePath(rawTargetPath);
            if (IsExcludedPath(targetPath)
                || string.Equals(sourcePath, targetPath, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            edges.Add((sourcePath, targetPath));
        }
    }
}

var payload = new
{
    edges = edges
        .OrderBy(e => e.Source, StringComparer.OrdinalIgnoreCase)
        .ThenBy(e => e.Target, StringComparer.OrdinalIgnoreCase)
        .Select(e => new { source = e.Source, target = e.Target }),
};

Console.WriteLine(JsonSerializer.Serialize(payload));

file sealed class EdgeComparer : IEqualityComparer<(string Source, string Target)>
{
    public static readonly EdgeComparer OrdinalIgnoreCase = new();

    public bool Equals((string Source, string Target) x, (string Source, string Target) y)
    {
        return StringComparer.OrdinalIgnoreCase.Equals(x.Source, y.Source)
            && StringComparer.OrdinalIgnoreCase.Equals(x.Target, y.Target);
    }

    public int GetHashCode((string Source, string Target) obj)
    {
        int sourceHash = StringComparer.OrdinalIgnoreCase.GetHashCode(obj.Source ?? string.Empty);
        int targetHash = StringComparer.OrdinalIgnoreCase.GetHashCode(obj.Target ?? string.Empty);
        return HashCode.Combine(sourceHash, targetHash);
    }
}
