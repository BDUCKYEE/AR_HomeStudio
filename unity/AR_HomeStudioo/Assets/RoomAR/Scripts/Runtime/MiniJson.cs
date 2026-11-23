using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace RoomAR
{
    /// <summary>
    /// 작은 JSON 파서 (외부 패키지 의존 없음). 결과 타입:
    /// Dictionary&lt;string, object&gt;, List&lt;object&gt;, double, string, bool, null.
    /// </summary>
    public static class MiniJson
    {
        public static object Parse(string json)
        {
            if (json == null) return null;
            int i = 0;
            var v = Value(json, ref i);
            Ws(json, ref i);
            if (i < json.Length) throw new FormatException($"JSON 끝에 남은 문자 (위치 {i})");
            return v;
        }

        static void Ws(string s, ref int i)
        {
            while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
        }

        static object Value(string s, ref int i)
        {
            Ws(s, ref i);
            if (i >= s.Length) throw new FormatException("JSON이 중간에 끝남");
            char c = s[i];
            if (c == '{') return Obj(s, ref i);
            if (c == '[') return Arr(s, ref i);
            if (c == '"') return Str(s, ref i);
            if (Lit(s, ref i, "true")) return true;
            if (Lit(s, ref i, "false")) return false;
            if (Lit(s, ref i, "null")) return null;
            if (Lit(s, ref i, "NaN")) return double.NaN;
            return Num(s, ref i);
        }

        static bool Lit(string s, ref int i, string lit)
        {
            if (string.CompareOrdinal(s, i, lit, 0, lit.Length) != 0) return false;
            i += lit.Length;
            return true;
        }

        static Dictionary<string, object> Obj(string s, ref int i)
        {
            var d = new Dictionary<string, object>();
            i++; // {
            Ws(s, ref i);
            if (i < s.Length && s[i] == '}') { i++; return d; }
            while (true)
            {
                Ws(s, ref i);
                string k = Str(s, ref i);
                Ws(s, ref i);
                if (i >= s.Length || s[i] != ':') throw new FormatException($"':' 필요 (위치 {i})");
                i++;
                d[k] = Value(s, ref i);
                Ws(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == '}') { i++; return d; }
                throw new FormatException($"',' 또는 '}}' 필요 (위치 {i})");
            }
        }

        static List<object> Arr(string s, ref int i)
        {
            var l = new List<object>();
            i++; // [
            Ws(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return l; }
            while (true)
            {
                l.Add(Value(s, ref i));
                Ws(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == ']') { i++; return l; }
                throw new FormatException($"',' 또는 ']' 필요 (위치 {i})");
            }
        }

        static string Str(string s, ref int i)
        {
            if (i >= s.Length || s[i] != '"') throw new FormatException($"문자열 필요 (위치 {i})");
            i++;
            var sb = new StringBuilder();
            while (i < s.Length)
            {
                char c = s[i++];
                if (c == '"') return sb.ToString();
                if (c != '\\') { sb.Append(c); continue; }
                if (i >= s.Length) break;
                char e = s[i++];
                switch (e)
                {
                    case 'n': sb.Append('\n'); break;
                    case 't': sb.Append('\t'); break;
                    case 'r': sb.Append('\r'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'u':
                        sb.Append((char)Convert.ToInt32(s.Substring(i, 4), 16));
                        i += 4;
                        break;
                    default: sb.Append(e); break;
                }
            }
            throw new FormatException("문자열이 닫히지 않음");
        }

        static double Num(string s, ref int i)
        {
            int st = i;
            while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0) i++;
            if (i == st) throw new FormatException($"알 수 없는 값 (위치 {i}: '{s[i]}')");
            return double.Parse(s.Substring(st, i - st), NumberStyles.Float, CultureInfo.InvariantCulture);
        }

        // ---- 읽기 도우미 ----

        public static Dictionary<string, object> AsObj(object o) => o as Dictionary<string, object>;
        public static List<object> AsList(object o) => o as List<object>;

        public static object Get(Dictionary<string, object> d, params string[] keys)
        {
            if (d == null) return null;
            foreach (var k in keys)
                if (d.TryGetValue(k, out var v) && v != null) return v;
            return null;
        }

        public static float? GetFloat(Dictionary<string, object> d, params string[] keys)
        {
            var v = Get(d, keys);
            if (v is double x) return (float)x;
            if (v is bool b) return b ? 1f : 0f;
            if (v is string str && float.TryParse(str, NumberStyles.Float, CultureInfo.InvariantCulture, out var f)) return f;
            return null;
        }

        public static string GetString(Dictionary<string, object> d, params string[] keys) => Get(d, keys) as string;

        /// <summary>숫자 배열 → float[] (숫자가 아닌 원소가 있으면 null).</summary>
        public static float[] GetFloats(Dictionary<string, object> d, params string[] keys) => ToFloats(Get(d, keys));

        public static float[] ToFloats(object o)
        {
            if (o is not List<object> l) return null;
            var r = new float[l.Count];
            for (int i = 0; i < l.Count; i++)
            {
                if (l[i] is double x) r[i] = (float)x;
                else return null;
            }
            return r;
        }
    }
}
