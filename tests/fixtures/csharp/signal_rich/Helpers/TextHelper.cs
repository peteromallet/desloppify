namespace SignalRich.Helpers;

public class TextHelper
{
    public string Normalize(string input)
    {
        return input.Trim().ToLowerInvariant();
    }
}
