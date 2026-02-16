using Cycle.B;

namespace Cycle.A;

public class AService
{
    public string Read(BService svc)
    {
        return svc.Name;
    }
}
