using SignalRich.Extensions;
using SignalRich.Helpers;
using SignalRich.Infra;
using SignalRich.Models;
using SignalRich.Security;

namespace SignalRich.Tools;

public class OrphanComplexService
{
    private readonly int _a01 = 1;
    private readonly int _a02 = 2;
    private readonly int _a03 = 3;
    private readonly int _a04 = 4;
    private readonly int _a05 = 5;
    private readonly int _a06 = 6;
    private readonly int _a07 = 7;
    private readonly int _a08 = 8;
    private readonly int _a09 = 9;
    private readonly int _a10 = 10;
    private readonly int _a11 = 11;

    public string Analyze(Widget widget, Clock clock, TextHelper helper, NameFormatter formatter, InsecureSql security)
    {
        if (widget != null)
        {
            if (clock != null)
            {
                if (helper != null)
                {
                    if (formatter != null)
                    {
                        if (security != null)
                        {
                            if (_a01 > 0)
                            {
                                if (_a02 > 0)
                                {
                                    if (_a03 > 0)
                                    {
                                        if (_a04 > 0)
                                        {
                                            if (_a05 > 0)
                                            {
                                                return formatter.Format(helper.Normalize(widget.Name));
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        return string.Empty;
    }

    public int M01() { return _a01; }
    public int M02() { return _a02; }
    public int M03() { return _a03; }
    public int M04() { return _a04; }
    public int M05() { return _a05; }
    public int M06() { return _a06; }
    public int M07() { return _a07; }
    public int M08() { return _a08; }
    public int M09() { return _a09; }
    public int M10() { return _a10; }
    public int M11() { return _a11; }
    public int M12() { return _a01 + _a02; }
    public int M13() { return _a02 + _a03; }
    public int M14() { return _a03 + _a04; }
    public int M15() { return _a04 + _a05; }
    public int M16() { return _a05 + _a06; }
    public int M17() { return _a06 + _a07; }
    public int M18() { return _a07 + _a08; }
    public int M19() { return _a08 + _a09; }
    public int M20() { return _a09 + _a10; }
    public int M21() { return _a10 + _a11; }
    public int M22() { return _a11 + _a01; }
}
