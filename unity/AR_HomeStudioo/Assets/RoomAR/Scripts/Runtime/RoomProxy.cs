using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace RoomAR
{
    /// <summary>
    /// proxy.json(평면 + 상자로 근사한 방) → 보이지 않는 BoxCollider 묶음.
    ///
    /// 좌표: proxy.json은 방 메시와 같은 월드 좌표계(glTF 규약: 오른손, Y 위, 미터)입니다.
    ///   glTF → Unity 변환은 glTFast와 같은 규칙(X축 반전)으로 이 파일의 ToUnity* 함수에서만 한 번 합니다.
    ///   (최상위 "frame"에 "unity"가 들어 있으면 변환하지 않음)
    ///
    /// interfaces.md에 형식이 확정되기 전이라 아래 표기를 모두 받습니다 (모든 좌표·방향은 glTF 월드):
    ///   planes/floor/ceiling: { "label", "normal":[x,y,z], "point":[x,y,z] | "d" (n·p + d = 0) | "equation":[a,b,c,d],
    ///                           "polygon"/"corners"/"points":[[x,y,z],...] | "center"+"size":[w,h] (없으면 방 전체를 덮는 크기) }
    ///   boxes/objects/bboxes: { "label", "center":[x,y,z], "size":[sx,sy,sz] | "half_size"/"extent" | "min"+"max",
    ///                           회전 "yaw_deg"(Y축, 도) | "yaw"(라디안) | "rotation"/"quaternion":[x,y,z,w] | "R":[[3×3]] }
    ///   walls: { "start"/"a":[x,y,z]|[x,z], "end"/"b", "height", "base"(바닥 y), "thickness" }  (SpatialLM 벽 형식)
    ///   shapes/primitives: 위 항목들에 "type":"plane"|"box"|"wall"을 붙인 평면 목록
    /// 평면·벽 충돌체는 면 뒤쪽(법선 반대쪽)으로 두께를 갖는 얇은 상자이므로 표면 위치는 그대로입니다.
    /// 벽·바닥·천장(또는 크기 없는 무한 평면)은 법선을 방 중심 쪽으로 맞춥니다.
    /// </summary>
    public static class RoomProxy
    {
        public const float DefaultThickness = 0.3f;

        public enum Kind { Plane, Box, Wall }

        public class Shape
        {
            public Kind Kind;
            public string Label;
            public Vector3 Center;      // Unity 좌표
            public Quaternion Rotation; // Unity 좌표
            public Vector3 Size;        // 로컬 축 크기 (m)
        }

        public class Result
        {
            public List<Shape> Shapes = new();
            public List<string> Warnings = new();
            public int Ignored;
            public string Summary =>
                $"평면 {Shapes.Count(s => s.Kind == Kind.Plane)} · 벽 {Shapes.Count(s => s.Kind == Kind.Wall)} · 상자 {Shapes.Count(s => s.Kind == Kind.Box)}" +
                (Ignored > 0 ? $" · 무시 {Ignored}" : "") + (Warnings.Count > 0 ? $" · 경고 {Warnings.Count}" : "");
        }

        static bool mirror = true;

        // ---- glTF → Unity (X축 반전, glTFast와 같은 규칙). 이 세 함수에서만 변환합니다. ----
        static Vector3 ToUnityP(float[] a) => mirror ? new Vector3(-a[0], a[1], a[2]) : new Vector3(a[0], a[1], a[2]);
        static Vector3 ToUnityDir(Vector3 g) => mirror ? new Vector3(-g.x, g.y, g.z) : g;
        static Quaternion ToUnityQ(float[] q) => mirror ? new Quaternion(q[0], -q[1], -q[2], q[3]) : new Quaternion(q[0], q[1], q[2], q[3]);

        /// <param name="room">원본 방 메시의 Unity 월드 범위 (법선 방향 맞추기, 무한 평면 크기에 사용)</param>
        public static Result Parse(string json, Bounds room)
        {
            var r = new Result();
            var root = MiniJson.AsObj(MiniJson.Parse(json));
            if (root == null) { r.Warnings.Add("최상위가 객체가 아님"); return r; }

            string frame = (MiniJson.GetString(root, "frame", "coordinate_system", "coords") ?? "gltf").ToLowerInvariant();
            mirror = !frame.Contains("unity");
            if (frame.Contains("z_up") || frame.Contains("zup")) r.Warnings.Add($"frame={frame}: Z 위 좌표로 보임 (glTF Y 위 필요)");

            void Each(string key, Kind? kind)
            {
                var v = MiniJson.Get(root, key);
                if (v is Dictionary<string, object> single) Add(single, kind, key);
                else if (v is List<object> list) foreach (var o in list) Add(MiniJson.AsObj(o), kind, key);
            }

            void Add(Dictionary<string, object> d, Kind? kind, string key)
            {
                if (d == null) { r.Ignored++; return; }
                string label = MiniJson.GetString(d, "label", "class", "category", "name") ?? key;
                Kind? k = kind ?? TypeOf(MiniJson.GetString(d, "type", "kind", "shape"));
                try
                {
                    Shape s = k switch
                    {
                        Kind.Plane => PlaneShape(d, label, room, key),
                        Kind.Box => BoxShape(d, label),
                        Kind.Wall => WallShape(d, label, room),
                        _ => null,
                    };
                    if (s == null) { r.Ignored++; r.Warnings.Add($"{key}/{label}: 형식을 알 수 없음"); }
                    else r.Shapes.Add(s);
                }
                catch (Exception e) { r.Ignored++; r.Warnings.Add($"{key}/{label}: {e.Message}"); }
            }

            Each("floor", Kind.Plane);
            Each("ceiling", Kind.Plane);
            Each("planes", Kind.Plane);
            Each("walls", Kind.Wall);
            Each("boxes", Kind.Box);
            Each("objects", Kind.Box);
            Each("bboxes", Kind.Box);
            Each("shapes", null);
            Each("primitives", null);
            foreach (var skip in new[] { "doors", "windows" })
                if (MiniJson.Get(root, skip) is List<object> l && l.Count > 0) { r.Ignored += l.Count; r.Warnings.Add($"{skip} {l.Count}개는 충돌체로 만들지 않음"); }
            if (r.Shapes.Count == 0) r.Warnings.Add("충돌체로 만들 항목이 없음");
            return r;
        }

        static Kind? TypeOf(string t)
        {
            if (t == null) return null;
            t = t.ToLowerInvariant();
            if (t.Contains("wall")) return Kind.Wall;
            if (t.Contains("plane") || t.Contains("floor") || t.Contains("ceiling")) return Kind.Plane;
            if (t.Contains("box") || t.Contains("cuboid") || t.Contains("obb") || t.Contains("aabb")) return Kind.Box;
            return null;
        }

        static bool IsBoundaryLabel(string label)
        {
            label = (label ?? "").ToLowerInvariant();
            return label.Contains("floor") || label.Contains("wall") || label.Contains("ceiling") ||
                   label.Contains("바닥") || label.Contains("벽") || label.Contains("천장");
        }

        static Shape PlaneShape(Dictionary<string, object> d, string label, Bounds room, string key)
        {
            float[] eq = MiniJson.GetFloats(d, "equation", "plane", "abcd");
            float[] nG = MiniJson.GetFloats(d, "normal", "n") ?? (eq != null && eq.Length == 4 ? eq.Take(3).ToArray() : null);
            var polyList = MiniJson.AsList(MiniJson.Get(d, "polygon", "corners", "points", "vertices"));
            var poly = polyList?.Select(MiniJson.ToFloats).Where(a => a != null && a.Length >= 3).Select(ToUnityP).ToList();
            if (poly != null && poly.Count < 3) poly = null;

            Vector3 n;
            if (nG != null && nG.Length >= 3) n = ToUnityDir(new Vector3(nG[0], nG[1], nG[2]));
            else if (poly != null) n = Vector3.Cross(poly[1] - poly[0], poly[2] - poly[0]); // 법선이 없으면 다각형에서 (방향은 아래에서 맞춤)
            else throw new Exception("normal 없음");
            float len = n.magnitude;
            if (len < 1e-6f) throw new Exception("normal 길이 0");
            n /= len;

            Vector3 p;
            float[] pt = MiniJson.GetFloats(d, "point", "origin", "center", "centroid");
            float? dd = MiniJson.GetFloat(d, "d", "offset");
            if (pt != null && pt.Length >= 3) p = ToUnityP(pt);
            else if (poly != null) p = poly.Aggregate(Vector3.zero, (a, b) => a + b) / poly.Count;
            else if (dd != null || (eq != null && eq.Length == 4))
            {
                // glTF: n·x + d = 0, |n| = len  → 평면 위 점 = -d/|n| · n̂ (반전은 n̂에 이미 반영, 거리는 그대로)
                float dv = dd ?? eq[3];
                p = -dv / len * n;
            }
            else throw new Exception("point/d/polygon 없음");

            bool infinite = poly == null && MiniJson.GetFloats(d, "size", "extent") == null;
            if (IsBoundaryLabel(label) || IsBoundaryLabel(key) || infinite)
            {
                if (Vector3.Dot(room.center - p, n) < 0) n = -n; // 방 경계면: 법선을 방 안쪽으로
            }

            // 면 위 기준축: 수평면이면 u = X를 면에 투영, 수직면이면 u = 수평 방향
            Vector3 u = Mathf.Abs(n.y) > 0.7f ? Vector3.ProjectOnPlane(Vector3.right, n) : Vector3.Cross(Vector3.up, n);
            u.Normalize();
            Vector3 v = Vector3.Cross(n, u).normalized;

            IEnumerable<Vector3> pts;
            float[] size2 = MiniJson.GetFloats(d, "size", "extent");
            if (poly != null) pts = poly;
            else if (size2 != null && size2.Length >= 2)
                pts = new[] { p - u * size2[0] / 2 - v * size2[1] / 2, p + u * size2[0] / 2 + v * size2[1] / 2 };
            else
            {
                // 무한 평면: 방 범위(+0.5m)를 면에 투영한 크기
                var b = room; b.Expand(1.0f);
                pts = Enumerable.Range(0, 8).Select(i => new Vector3(i % 2 == 0 ? b.min.x : b.max.x, (i / 2) % 2 == 0 ? b.min.y : b.max.y, i / 4 == 0 ? b.min.z : b.max.z));
            }
            float u0 = float.MaxValue, u1 = float.MinValue, v0 = float.MaxValue, v1 = float.MinValue;
            foreach (var q in pts)
            {
                float a = Vector3.Dot(q - p, u), c = Vector3.Dot(q - p, v);
                u0 = Mathf.Min(u0, a); u1 = Mathf.Max(u1, a); v0 = Mathf.Min(v0, c); v1 = Mathf.Max(v1, c);
            }
            float t = MiniJson.GetFloat(d, "thickness") ?? DefaultThickness;
            Vector3 surfaceCenter = p + u * (u0 + u1) / 2 + v * (v0 + v1) / 2;
            return new Shape
            {
                Kind = Kind.Plane, Label = label,
                Center = surfaceCenter - n * (t / 2f),
                Rotation = LocalFrame(u, v, n),
                Size = new Vector3(Mathf.Max(0.01f, u1 - u0), Mathf.Max(0.01f, v1 - v0), t),
            };
        }

        /// <summary>로컬 x→u, y→v, z→n 이 되도록 회전 (v = n×u 이므로 LookRotation의 오른쪽 축 v×n = u).</summary>
        static Quaternion LocalFrame(Vector3 u, Vector3 v, Vector3 n) => Quaternion.LookRotation(n, v);

        static Shape BoxShape(Dictionary<string, object> d, string label)
        {
            Vector3 c, size;
            float[] mn = MiniJson.GetFloats(d, "min"), mx = MiniJson.GetFloats(d, "max");
            float[] ct = MiniJson.GetFloats(d, "center", "position", "centroid");
            float[] sz = MiniJson.GetFloats(d, "size", "scale", "dimensions");
            float[] hs = MiniJson.GetFloats(d, "half_size", "half_extent", "extent", "half_extents");
            if (ct != null && ct.Length >= 3) c = ToUnityP(ct);
            else if (mn != null && mx != null && mn.Length >= 3 && mx.Length >= 3)
                c = ToUnityP(new[] { (mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2 });
            else throw new Exception("center 또는 min/max 없음");

            if (sz != null && sz.Length >= 3) size = new Vector3(sz[0], sz[1], sz[2]);
            else if (hs != null && hs.Length >= 3) size = new Vector3(hs[0], hs[1], hs[2]) * 2f;
            else if (mn != null && mx != null) size = new Vector3(Mathf.Abs(mx[0] - mn[0]), Mathf.Abs(mx[1] - mn[1]), Mathf.Abs(mx[2] - mn[2]));
            else throw new Exception("size 없음");
            size = new Vector3(Mathf.Abs(size.x), Mathf.Abs(size.y), Mathf.Abs(size.z));

            Quaternion rot = Quaternion.identity;
            float[] q = MiniJson.GetFloats(d, "rotation", "quaternion", "quat");
            var rList = MiniJson.AsList(MiniJson.Get(d, "R", "rotation_matrix"));
            float? yawDeg = MiniJson.GetFloat(d, "yaw_deg", "yaw_degrees", "angle_deg");
            float? yawRad = MiniJson.GetFloat(d, "yaw", "angle", "heading");
            if (q != null && q.Length == 4) rot = ToUnityQ(q);
            else if (rList != null && rList.Count == 3)
            {
                // 3×3 행 우선 행렬, 열 = 로컬 축의 glTF 월드 방향
                var rows = rList.Select(MiniJson.ToFloats).ToArray();
                if (rows.Any(rw => rw == null || rw.Length != 3)) throw new Exception("R은 3×3이어야 함");
                Vector3 col(int j) => new(rows[0][j], rows[1][j], rows[2][j]);
                rot = Quaternion.LookRotation(ToUnityDir(col(2)), ToUnityDir(col(1)));
            }
            else if (yawDeg != null || yawRad != null)
            {
                // glTF에서 +Y축 θ 회전 → X 반전 후 Unity에서는 -θ
                float deg = yawDeg ?? yawRad.Value * Mathf.Rad2Deg;
                rot = Quaternion.Euler(0f, mirror ? -deg : deg, 0f);
            }
            return new Shape { Kind = Kind.Box, Label = label, Center = c, Rotation = rot, Size = size };
        }

        static Shape WallShape(Dictionary<string, object> d, string label, Bounds room)
        {
            float[] a = MiniJson.GetFloats(d, "start", "a", "p0", "from");
            float[] b = MiniJson.GetFloats(d, "end", "b", "p1", "to");
            if (a == null || b == null) return d.ContainsKey("normal") ? PlaneShape(d, label, room, "wall") : null;
            // 2D [x, z] 허용
            if (a.Length == 2) a = new[] { a[0], 0f, a[1] };
            if (b.Length == 2) b = new[] { b[0], 0f, b[1] };
            Vector3 pa = ToUnityP(a), pb = ToUnityP(b);
            float baseY = MiniJson.GetFloat(d, "base", "base_y", "bottom") ?? Mathf.Min(pa.y, pb.y, 0f);
            float h = MiniJson.GetFloat(d, "height") ?? Mathf.Max(0.5f, room.max.y - baseY);
            float t = MiniJson.GetFloat(d, "thickness") ?? DefaultThickness;
            Vector3 dir = pb - pa; dir.y = 0;
            float len = dir.magnitude;
            if (len < 1e-3f) throw new Exception("벽 길이 0");
            dir /= len;
            Vector3 n = Vector3.Cross(Vector3.up, dir).normalized;
            Vector3 mid = (pa + pb) / 2f; mid.y = baseY + h / 2f;
            Vector3 toRoom = room.center - mid; toRoom.y = 0;
            if (Vector3.Dot(toRoom, n) < 0) n = -n; // 방 안쪽
            return new Shape
            {
                Kind = Kind.Wall, Label = label,
                Center = mid - n * (t / 2f),
                Rotation = Quaternion.LookRotation(n, Vector3.up),
                Size = new Vector3(len + 2 * t, h, t), // 모서리 틈이 생기지 않게 양 끝을 두께만큼 연장
            };
        }

        /// <summary>parent 아래에 상자 충돌체를 만듭니다. 렌더러는 미리보기용으로 꺼 둡니다.</summary>
        public static GameObject Build(Result r, Transform parent, string name, Material preview)
        {
            var root = new GameObject(name);
            root.transform.SetParent(parent, false);
            var mpb = new MaterialPropertyBlock();
            foreach (var s in r.Shapes)
            {
                var go = GameObject.CreatePrimitive(PrimitiveType.Cube); // BoxCollider(1×1×1) 포함
                go.name = $"{s.Kind}: {s.Label}";
                go.transform.SetParent(root.transform, false);
                go.transform.SetPositionAndRotation(s.Center, s.Rotation);
                go.transform.localScale = s.Size;
                var mr = go.GetComponent<MeshRenderer>();
                if (preview != null) mr.sharedMaterial = preview;
                mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                mpb.SetColor("_BaseColor", s.Kind switch
                {
                    Kind.Plane => new Color(0.3f, 0.8f, 0.4f),
                    Kind.Wall => new Color(0.3f, 0.6f, 1f),
                    _ => new Color(1f, 0.6f, 0.2f),
                });
                mr.SetPropertyBlock(mpb);
                mr.enabled = false;
            }
            return root;
        }
    }
}
