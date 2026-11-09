using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace RoomAR
{
    /// <summary>
    /// 저장소 루트의 .env 읽기. 우선순위: 프로세스 환경 변수 → .env 파일.
    /// .env는 Application.dataPath(= unity/AR_HomeStudioo/Assets)에서 위로 올라가며 찾습니다.
    /// </summary>
    public static class EnvConfig
    {
        static Dictionary<string, string> cache;
        public static string EnvFilePath { get; private set; }

        public static string Get(string key, string fallback = null)
        {
            string v = Environment.GetEnvironmentVariable(key);
            if (!string.IsNullOrWhiteSpace(v)) return v.Trim();
            Load();
            return cache.TryGetValue(key, out v) && !string.IsNullOrWhiteSpace(v) ? v : fallback;
        }

        public static void Reload() { cache = null; Load(); }

        static void Load()
        {
            if (cache != null) return;
            cache = new Dictionary<string, string>();
            var dir = new DirectoryInfo(Application.dataPath);
            while (dir != null)
            {
                string p = Path.Combine(dir.FullName, ".env");
                if (File.Exists(p)) { EnvFilePath = p; break; }
                dir = dir.Parent;
            }
            if (EnvFilePath == null) return;

            foreach (var raw in File.ReadAllLines(EnvFilePath))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#")) continue;
                int eq = line.IndexOf('=');
                if (eq <= 0) continue;
                string k = line.Substring(0, eq).Trim();
                string val = line.Substring(eq + 1).Trim();
                if (val.Length >= 2 && (val[0] == '"' || val[0] == '\'') && val[val.Length - 1] == val[0])
                    val = val.Substring(1, val.Length - 2);
                cache[k] = val;
            }
        }

        /// <summary>SHARED_DIR/meshes 폴더. SHARED_DIR이 비어 있으면 null.</summary>
        public static string MeshesDir
        {
            get
            {
                string shared = Get("SHARED_DIR");
                return string.IsNullOrEmpty(shared) ? null : Path.Combine(shared, "meshes");
            }
        }
    }
}
