using UnityEngine;

namespace RoomAR
{
    /// <summary>
    /// 벽 ChArUco 보드 위치 표시 (얇은 사각형). interfaces.md 1절 기준:
    ///   월드 원점 = 보드 중심을 바닥에 수직으로 내린 점, +Y 위, +Z = 벽에서 방 안쪽, 보드 +X = 월드 +X.
    ///   → glTF 월드에서 보드 중심 = (0, h, 0), 보드 면은 XY 평면, 앞면이 +Z(방 안쪽)를 향함.
    /// Unity 변환 (glTFast와 같은 규칙, x → -x): 보드 중심 (0, h, 0)은 그대로, 보드 +X는 Unity -X.
    ///
    /// 구성: 종이(A3 297×420mm, 흰색) + 패턴 영역(칸 수 × 칸 크기, 어두운 색) + 보드 +X 표시(빨강)
    ///       + 원점 수직선(보드 중심 → 바닥) + 바닥 원점 십자. 모두 충돌체 없음.
    /// </summary>
    public class BoardMarker : MonoBehaviour
    {
        [SerializeField] Material material; // URP Unlit (색은 MaterialPropertyBlock)
        const float Thick = 0.003f;
        const float WallGap = 0.004f; // 벽 메시와 z-fighting 방지 (방 안쪽으로)

        GameObject root;
        public bool HasBoard { get; private set; }
        public string Summary { get; private set; } = "보드: 정보 없음";

        public void Apply(RoomMeshInfo info)
        {
            if (root != null) { DestroyObj(root); root = null; }
            HasBoard = info?.BoardCenterHeightM != null;
            if (!HasBoard)
            {
                Summary = $"보드: 위치 정보 없음 (scale_method={info?.ScaleMethod ?? "?"})";
                return;
            }

            float h = info.BoardCenterHeightM.Value;
            float sq = (info.SquareMm ?? 50f) / 1000f;
            float nx = info.SquaresX ?? 5f, ny = info.SquaresY ?? 7f;
            float pw = nx * sq, ph = ny * sq;                 // 패턴 영역 (세로 부착: 가로 5칸, 세로 7칸)
            float paperW = Mathf.Max(0.297f, pw + 0.02f), paperH = Mathf.Max(0.42f, ph + 0.02f);

            if (material == null)
            {
                var sh = Shader.Find("Universal Render Pipeline/Unlit");
                if (sh != null) material = new Material(sh);
            }

            root = new GameObject($"ChArUco Board (h={h:F3}m)");
            root.transform.SetParent(transform, false);

            // 보드는 z=0 평면(벽면)에 있고 앞면이 +Z. Unity에서도 z는 그대로.
            Vector3 c = new Vector3(0f, h, WallGap);
            Part("Paper",   c,                                   new Vector3(paperW, paperH, Thick),           new Color(0.95f, 0.95f, 0.9f));
            Part("Pattern", c + new Vector3(0, 0, Thick),        new Vector3(pw, ph, Thick),                   new Color(0.1f, 0.1f, 0.12f));
            // 보드 +X(인쇄물 오른쪽) = 월드 glTF +X = Unity -X
            Part("Board +X", c + new Vector3(-(paperW / 2f + 0.04f), 0, Thick), new Vector3(0.08f, 0.012f, Thick), new Color(0.9f, 0.15f, 0.15f));
            // 보드 중심 → 바닥 원점 수직선, 바닥 원점 십자, 방 안쪽(+Z) 표시
            Part("Plumb line", new Vector3(0, h / 2f, WallGap + 0.01f), new Vector3(0.006f, h, 0.006f), new Color(1f, 0.85f, 0.1f));
            Part("Origin X",   new Vector3(0, 0.002f, 0.08f),     new Vector3(0.16f, 0.003f, 0.01f),   new Color(1f, 0.85f, 0.1f));
            Part("Origin +Z",  new Vector3(0, 0.002f, 0.08f),     new Vector3(0.01f, 0.003f, 0.16f),   new Color(0.2f, 0.5f, 1f));

            string zNote = info.ZIntoRoom == false ? " · ⚠ z_into_room=false" : "";
            Summary = $"보드: 중심 높이 {h:F3}m, 패턴 {pw * 1000:F0}×{ph * 1000:F0}mm (B 표시){zNote}";
        }

        void Part(string name, Vector3 pos, Vector3 size, Color color)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = name;
            DestroyObj(go.GetComponent<Collider>());
            go.transform.SetParent(root.transform, false);
            go.transform.localPosition = pos;
            go.transform.localScale = size;
            var mr = go.GetComponent<MeshRenderer>();
            if (material != null) mr.sharedMaterial = material;
            mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            var mpb = new MaterialPropertyBlock();
            mpb.SetColor("_BaseColor", color);
            mr.SetPropertyBlock(mpb);
        }

        public void SetVisible(bool v) { if (root != null) root.SetActive(v); }
        public bool Visible => root != null && root.activeSelf;
        public Transform Root => root != null ? root.transform : null;

        static void DestroyObj(Object o)
        {
            if (o == null) return;
            if (Application.isPlaying) Destroy(o); else DestroyImmediate(o);
        }
    }
}
