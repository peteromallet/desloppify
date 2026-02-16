using SimpleApp.Services;

namespace SimpleApp;

public class Program
{
    public static void Main()
    {
        var greeter = new Greeter();
        greeter.SayHello("world");
    }
}
