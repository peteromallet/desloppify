namespace SignalRich.Infra;

public class Clock
{
    public long UnixNow()
    {
        return DateTimeOffset.UtcNow.ToUnixTimeSeconds();
    }
}
