using SignalRich.Security;
using SignalRich.Single;

namespace SignalRich;

public class Program
{
    public static void Main()
    {
        var single = new SingleUseFeature();
        var security = new InsecureSql();
        single.Run();
        security.Run("world");
    }
}
