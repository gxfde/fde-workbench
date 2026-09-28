import AppKit
import Foundation

guard CommandLine.arguments.count == 3 else {
    fputs("usage: render-macos-icon.swift <source.png> <output.png>\n", stderr)
    exit(2)
}

let sourceURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
guard let logo = NSImage(contentsOf: sourceURL) else {
    fputs("unable to read source logo\n", stderr)
    exit(1)
}

let pixels = 1024
guard let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: pixels,
    pixelsHigh: pixels,
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: 0,
    bitsPerPixel: 0
) else {
    fputs("unable to create icon bitmap\n", stderr)
    exit(1)
}

bitmap.size = NSSize(width: pixels, height: pixels)
guard let graphics = NSGraphicsContext(bitmapImageRep: bitmap) else {
    fputs("unable to create icon graphics context\n", stderr)
    exit(1)
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = graphics
graphics.imageInterpolation = .high

NSColor.clear.setFill()
NSRect(x: 0, y: 0, width: pixels, height: pixels).fill(using: .copy)

// Older macOS releases display the ICNS alpha exactly as authored. Keep the
// white tile and its shadow inside a transparent canvas instead of relying on
// the operating system to apply a rounded mask.
let tileRect = NSRect(x: 72, y: 84, width: 880, height: 880)
let tile = NSBezierPath(roundedRect: tileRect, xRadius: 205, yRadius: 205)
let context = graphics.cgContext
context.saveGState()
context.setShadow(offset: CGSize(width: 0, height: -18), blur: 30, color: NSColor.black.withAlphaComponent(0.18).cgColor)
NSColor.white.setFill()
tile.fill()
context.restoreGState()

// Use the transparent company mark unchanged and keep a generous safe area so
// the installed icon has the same optical size on old and new macOS versions.
let logoRect = NSRect(x: 166, y: 178, width: 692, height: 692)
logo.draw(in: logoRect, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high])

graphics.flushGraphics()
NSGraphicsContext.restoreGraphicsState()

guard let png = bitmap.representation(using: .png, properties: [:]) else {
    fputs("unable to encode icon PNG\n", stderr)
    exit(1)
}

try png.write(to: outputURL, options: .atomic)
