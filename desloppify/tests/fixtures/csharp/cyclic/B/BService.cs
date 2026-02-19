using Cycle.A;

namespace Cycle.B;

public class BService
{
    public string Name => "b";

    public string Read(AService svc)
    {
        return nameof(svc);
    }
}
