namespace SignalRich.Single;

public class SingleUseFeature
{
    private readonly string _name = "single";
    private readonly int _version = 1;
    private readonly bool _enabled = true;

    public string Describe()
    {
        return $"{_name}-{_version}-{_enabled}";
    }

    public void Run()
    {
        var text = Describe();
        if (text.Length > 0)
        {
            _ = text.Trim();
        }
    }
}
