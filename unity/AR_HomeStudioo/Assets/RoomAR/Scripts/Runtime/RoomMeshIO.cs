using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using GLTFast;
using UnityEngine;

namespace RoomAR
{
    /// <summary>
    /// 방 메시(.glb) 로딩과 통계. 실행 중 로더(RoomMeshLoader)와 에디터 검증기(RoomMeshValidator)가 함께 씁니다.
    ///
    /// 좌표: .glb는 glTF 규약(오른손, Y 위, 미터, 원점 = ChArUco 보드 중심).
    /// glTFast가 Unity 좌표계(왼손, Y 위)로 자동 변환(X축 반전)하므로 여기서는 축을 건드리지 않습니다.
    /// </summary>
    public static class RoomMeshIO
    {
        public const string LatestGlb = "room_latest.glb";
        public const string LatestJson = "room_latest.json";

        public class LoadResult : IDisposable
        {
            public bool Ok;
            public string Error;
            public GameObject Root;
            public GltfImport Import;   // 메시/머티리얼 소유. Dispose하면 메시가 파괴됨.
            public RoomMeshStats Stats;

            public void Dispose()
            {
                if (Root != null)
                {
                    if (Application.isPlaying) UnityEngine.Object.Destroy(Root);
                    else UnityEngine.Object.DestroyImmediate(Root);
                }
                Import?.Dispose();
                Root = null; Import = null;
            }
        }

        public static string LatestGlbPath => EnvConfig.MeshesDir == null ? null : Path.Combine(EnvConfig.MeshesDir, LatestGlb);
        public static string LatestJsonPath => EnvConfig.MeshesDir == null ? null : Path.Combine(EnvConfig.MeshesDir, LatestJson);

        /// <summary>
        /// .glb를 바이트로 읽어(쓰는 중인 파일과 충돌을 줄이기 위해 한 번에 읽음) parent 아래에 인스턴스화.
        /// 모든 MeshFilter에 MeshCollider를 붙이고, overrideMaterial이 있으면 모든 렌더러에 적용합니다.
        /// </summary>
        public static async Task<LoadResult> LoadAsync(string path, Transform parent, Material overrideMaterial, bool addColliders = true)
        {
            var result = new LoadResult();
            if (string.IsNullOrEmpty(path)) { result.Error = "SHARED_DIR이 .env에 설정되지 않았습니다."; return result; }
            if (!File.Exists(path)) { result.Error = $"파일 없음: {path}"; return result; }

            byte[] bytes;
            try
            {
                using var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                bytes = new byte[fs.Length];
                int read = 0;
                while (read < bytes.Length)
                {
                    int n = fs.Read(bytes, read, bytes.Length - read);
                    if (n <= 0) break;
                    read += n;
                }
                if (read != bytes.Length) { result.Error = $"읽기 중단 ({read}/{bytes.Length} bytes)"; return result; }
            }
            catch (Exception e) { result.Error = $"읽기 실패: {e.Message}"; return result; }

            var import = new GltfImport(deferAgent: new UninterruptedDeferAgent());
            bool ok;
            try { ok = await import.Load(bytes, new Uri(Path.GetFullPath(path))); }
            catch (Exception e) { import.Dispose(); result.Error = $"glTF 파싱 예외: {e.Message}"; return result; }
            if (!ok) { import.Dispose(); result.Error = "glTF 로딩 실패 (파일이 쓰는 중이거나 손상됨)"; return result; }

            var root = new GameObject($"RoomMesh ({Path.GetFileName(path)})");
            root.transform.SetParent(parent, false);
            try { ok = await import.InstantiateMainSceneAsync(root.transform); }
            catch (Exception e) { ok = false; result.Error = $"인스턴스화 예외: {e.Message}"; }
            if (!ok)
            {
                result.Root = root; result.Import = import; result.Dispose();
                result.Error ??= "인스턴스화 실패";
                return result;
            }

            foreach (var mf in root.GetComponentsInChildren<MeshFilter>(true))
            {
                if (mf.sharedMesh == null) continue;
                var mr = mf.GetComponent<MeshRenderer>();
                if (mr != null && overrideMaterial != null)
                {
                    var mats = new Material[Mathf.Max(1, mf.sharedMesh.subMeshCount)];
                    for (int i = 0; i < mats.Length; i++) mats[i] = overrideMaterial;
                    mr.sharedMaterials = mats;
                    mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                }
                if (addColliders)
                {
                    var mc = mf.gameObject.AddComponent<MeshCollider>();
                    mc.sharedMesh = mf.sharedMesh; // glTFast는 UploadMeshData(false) → 읽기 가능 메시
                }
                mf.gameObject.isStatic = false;
            }

            result.Ok = true;
            result.Root = root;
            result.Import = import;
            result.Stats = RoomMeshStats.Compute(root);
            return result;
        }

        /// <summary>room_latest.json 원문 (없으면 null).</summary>
        public static string ReadLatestJson()
        {
            string p = LatestJsonPath;
            try { return p != null && File.Exists(p) ? File.ReadAllText(p) : null; }
            catch { return null; }
        }

        static readonly Regex SampleValue = new(@"""[^""]*""\s*:\s*""[^""]*(example|sample|예제|샘플|demo)[^""]*""", RegexOptions.IgnoreCase);
        static readonly Regex SampleFlag = new(@"""[^""]*(example|sample|예제|샘플)[^""]*""\s*:\s*true", RegexOptions.IgnoreCase);

        /// <summary>
        /// room_latest.json이 예제 이미지로 만든 메시라고 표시하는지.
        /// 스키마가 정해지기 전이라 문자열 값/불리언 키에 example/sample/예제가 있는지로 판단합니다.
        /// </summary>
        public static bool IsSampleMesh(string json)
        {
            if (string.IsNullOrEmpty(json)) return false;
            // cv 규약: "source": "sample" | "real" 가 있으면 그것을 우선
            var m = SourceField.Match(json);
            if (m.Success) return !m.Groups[1].Value.Equals("real", StringComparison.OrdinalIgnoreCase);
            return SampleValue.IsMatch(json) || SampleFlag.IsMatch(json);
        }

        static readonly Regex SourceField = new(@"""source""\s*:\s*""([^""]*)""", RegexOptions.IgnoreCase);

        /// <summary>room_latest.json에서 Unity가 쓰는 필드만 뽑습니다 (interfaces.md 2절). 없는 값은 null.</summary>
        public static RoomMeshInfo ParseInfo(string json)
        {
            var info = new RoomMeshInfo { Raw = json };
            if (string.IsNullOrEmpty(json)) return info;
            info.Source = Str(json, "source");
            info.ScaleMethod = Str(json, "scale_method");
            info.File = Str(json, "file");
            info.BoardCenterHeightM = Num(json, "board_center_height_m");
            info.SquareMm = Num(json, "square_mm");
            info.SquaresX = Num(json, "squares_x");
            info.SquaresY = Num(json, "squares_y");
            var z = Regex.Match(json, @"""z_into_room""\s*:\s*(true|false)", RegexOptions.IgnoreCase);
            if (z.Success) info.ZIntoRoom = z.Groups[1].Value.ToLowerInvariant() == "true";
            info.IsSample = IsSampleMesh(json);
            return info;
        }

        static string Str(string json, string key)
        {
            var m = Regex.Match(json, $@"""{Regex.Escape(key)}""\s*:\s*""([^""]*)""");
            return m.Success ? m.Groups[1].Value : null;
        }

        static float? Num(string json, string key)
        {
            var m = Regex.Match(json, $@"""{Regex.Escape(key)}""\s*:\s*(null|-?[0-9.]+(?:[eE][-+]?[0-9]+)?)");
            if (!m.Success || m.Groups[1].Value == "null") return null;
            return float.TryParse(m.Groups[1].Value, System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out var v) ? v : null;
        }

        /// <summary>glb 옆의 같은 이름 .json (room_latest.glb → room_latest.json).</summary>
        public static string ReadSiblingJson(string glbPath)
        {
            try
            {
                if (string.IsNullOrEmpty(glbPath)) return null;
                string p = Path.ChangeExtension(glbPath, ".json");
                return File.Exists(p) ? File.ReadAllText(p) : null;
            }
            catch { return null; }
        }
    }

    public class RoomMeshInfo
    {
        public string Raw, Source, ScaleMethod, File;
        public bool IsSample;
        /// <summary>바닥에서 벽 보드 중심까지 높이 (m). charuco 스케일이 아니면 null.</summary>
        public float? BoardCenterHeightM;
        public float? SquareMm, SquaresX, SquaresY;
        public bool? ZIntoRoom;
    }

    /// <summary>인스턴스화된 메시의 월드(Unity) 좌표 통계.</summary>
    public struct RoomMeshStats
    {
        public int MeshCount;
        public int VertexCount;
        public long TriangleCount;
        public bool HasVertexColors;
        public Bounds WorldBounds;
        public float FloorP1;        // 정점 y 1% 분위수 (바닥 추정)
        public float FloorP5;
        public float NearFloorRatio; // |y| < 3cm 정점 비율

        public static RoomMeshStats Compute(GameObject root)
        {
            var s = new RoomMeshStats();
            bool first = true;
            var ys = new List<float>();
            var tmp = new List<Vector3>();
            foreach (var mf in root.GetComponentsInChildren<MeshFilter>(true))
            {
                var m = mf.sharedMesh;
                if (m == null) continue;
                s.MeshCount++;
                s.VertexCount += m.vertexCount;
                for (int i = 0; i < m.subMeshCount; i++)
                    if (m.GetTopology(i) == MeshTopology.Triangles) s.TriangleCount += (long)m.GetIndexCount(i) / 3;
                if (m.HasVertexAttribute(UnityEngine.Rendering.VertexAttribute.Color)) s.HasVertexColors = true;

                if (!m.isReadable) continue;
                m.GetVertices(tmp);
                var l2w = mf.transform.localToWorldMatrix;
                foreach (var v in tmp)
                {
                    var w = l2w.MultiplyPoint3x4(v);
                    if (first) { s.WorldBounds = new Bounds(w, Vector3.zero); first = false; }
                    else s.WorldBounds.Encapsulate(w);
                    ys.Add(w.y);
                }
            }
            if (ys.Count > 0)
            {
                ys.Sort();
                s.FloorP1 = ys[Mathf.Clamp((int)(ys.Count * 0.01f), 0, ys.Count - 1)];
                s.FloorP5 = ys[Mathf.Clamp((int)(ys.Count * 0.05f), 0, ys.Count - 1)];
                int near = 0;
                foreach (var y in ys) if (Mathf.Abs(y) < 0.03f) near++;
                s.NearFloorRatio = (float)near / ys.Count;
            }
            return s;
        }

        public override string ToString()
        {
            var b = WorldBounds;
            return $"삼각형 {TriangleCount:N0} · 정점 {VertexCount:N0} · 메시 {MeshCount} · 정점색 {(HasVertexColors ? "있음" : "없음")}\n" +
                   $"크기 X {b.size.x:F2} × Y {b.size.y:F2} × Z {b.size.z:F2} m · min y {b.min.y:F3} · 바닥 p1 {FloorP1:F3} m";
        }
    }
}
