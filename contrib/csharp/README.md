# C# Roslyn Graph Emitter

This folder contains a small C# console utility that emits dependency graph edges for Desloppify.

## Project

- `RoslynGraphEmitter/` - regular .NET console app (no `dotnet-script`).

## Run manually

From repository root:

```bash
dotnet run --project contrib/csharp/RoslynGraphEmitter/RoslynGraphEmitter.csproj -- .
```

Output format:

```json
{"edges":[{"source":"...","target":"..."}]}
```

## Use with Desloppify

```bash
desloppify --lang csharp detect deps --path . \
  --roslyn-cmd "dotnet run --project contrib/csharp/RoslynGraphEmitter/RoslynGraphEmitter.csproj -- {path}"
```

```bash
desloppify --lang csharp scan --path . \
  --roslyn-cmd "dotnet run --project contrib/csharp/RoslynGraphEmitter/RoslynGraphEmitter.csproj -- {path}"
```

If the Roslyn command fails, Desloppify automatically falls back to heuristic graphing.
