import { describe, expect, it } from "vitest"

import { MAX_UPLOAD_SIZE_BYTES, decodeTextPreview, filePreviewKind, fileTooLarge, versionCanBePreviewed } from "../../src/renderer/src/files/fileCapabilities"

describe("file capabilities", () => {
  it("allows preview only for supported extensions", () => {
    expect(versionCanBePreviewed({ id: "1", version_number: 1, status: "available", scan_status: "not_required", original_filename: "说明.md" })).toBe(true)
    expect(versionCanBePreviewed({ id: "2", version_number: 2, status: "available", scan_status: "not_required", original_filename: "设计.psd" })).toBe(false)
    expect(versionCanBePreviewed({ id: "3", version_number: 3, status: "failed", scan_status: "not_required", original_filename: "说明.pdf" })).toBe(false)
    expect(versionCanBePreviewed({ id: "4", version_number: 1, status: "available", scan_status: "not_required", original_filename: "报表.xlsx" })).toBe(true)
  })

  it("selects a renderer for every previewable non-DOCX format", () => {
    expect(filePreviewKind("a.txt")).toBe("text")
    expect(filePreviewKind("a.md")).toBe("text")
    expect(filePreviewKind("a.csv")).toBe("text")
    expect(filePreviewKind("a.json")).toBe("text")
    expect(filePreviewKind("a.log")).toBe("text")
    expect(filePreviewKind("a.png")).toBe("image")
    expect(filePreviewKind("a.webp")).toBe("image")
    expect(filePreviewKind("a.pdf")).toBe("pdf")
    expect(filePreviewKind("a.xlsx")).toBe("converted-pdf")
    expect(filePreviewKind("a.pptx")).toBe("converted-pdf")
    expect(filePreviewKind("a.zip")).toBe("none")
  })

  it("decodes UTF-8, GB18030 and formats JSON text previews", () => {
    const utf8 = new TextEncoder().encode("中文 TXT").buffer
    expect(decodeTextPreview(utf8, "a.txt")).toBe("中文 TXT")
    const gb18030 = Uint8Array.from([0xd6, 0xd0, 0xce, 0xc4]).buffer
    expect(decodeTextPreview(gb18030, "a.txt")).toBe("中文")
    const json = new TextEncoder().encode('{"name":"test"}').buffer
    expect(decodeTextPreview(json, "a.json")).toContain('\n  "name": "test"\n')
  })

  it("uses a strict 100MB upload limit", () => {
    expect(fileTooLarge({ size: MAX_UPLOAD_SIZE_BYTES })).toBe(false)
    expect(fileTooLarge({ size: MAX_UPLOAD_SIZE_BYTES + 1 })).toBe(true)
  })
})
