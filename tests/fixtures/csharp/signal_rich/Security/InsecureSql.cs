using System.Data.SqlClient;
using System.Runtime.Serialization.Formatters.Binary;

namespace SignalRich.Security;

public class InsecureSql
{
    public void Run(string name)
    {
        var cmd = new SqlCommand($"SELECT * FROM Users WHERE Name = '{name}'");
        var token = new Random().Next().ToString();
        ServicePointManager.ServerCertificateValidationCallback += (sender, certificate, chain, sslPolicyErrors) => true;
        var formatter = new BinaryFormatter();
        _ = cmd;
        _ = token;
        _ = formatter;
    }
}
