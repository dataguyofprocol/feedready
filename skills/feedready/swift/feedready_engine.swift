import CoreImage
import CoreImage.CIFilterBuiltins
import Foundation
import Vision

let srgb = CGColorSpace(name: CGColorSpace.sRGB)!
let p3 = CGColorSpace(name: CGColorSpace.displayP3)!
let ctx = CIContext(options: [.workingColorSpace: CGColorSpace(name: CGColorSpace.extendedLinearSRGB)!])

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(1)
}

func load(_ path: String) -> CIImage {
    guard let img = CIImage(contentsOf: URL(fileURLWithPath: path), options: [.applyOrientationProperty: true]) else {
        fail("cannot read image: \(path)")
    }
    return img.transformed(by: CGAffineTransform(translationX: -img.extent.minX, y: -img.extent.minY)).settingProperties([:])
}

func loadMask(_ path: String) -> CIImage {
    guard let img = CIImage(contentsOf: URL(fileURLWithPath: path), options: [.colorSpace: NSNull()]) else {
        fail("cannot read mask: \(path)")
    }
    return img
}

func writePNG16(_ img: CIImage, _ path: String, _ space: CGColorSpace) {
    do {
        try ctx.writePNGRepresentation(of: img, to: URL(fileURLWithPath: path), format: .RGBA16, colorSpace: space)
    } catch { fail("write failed: \(path): \(error)") }
}

func writeMask(_ img: CIImage, _ path: String) {
    do {
        try ctx.writePNGRepresentation(of: img, to: URL(fileURLWithPath: path), format: .L8, colorSpace: CGColorSpace(name: CGColorSpace.linearGray)!)
    } catch { fail("write failed: \(path): \(error)") }
}

func writeJSON(_ obj: Any, _ path: String) {
    let data = try! JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys])
    try! data.write(to: URL(fileURLWithPath: path))
}

func decode(_ input: String, _ output: String) {
    let wide = CIImage(contentsOf: URL(fileURLWithPath: input))?.colorSpace?.isWideGamutRGB ?? false
    writePNG16(load(input), output, wide ? p3 : srgb)
}

func scaled(_ mask: CIImage, to extent: CGRect) -> CIImage {
    let sx = extent.width / mask.extent.width, sy = extent.height / mask.extent.height
    return mask.transformed(by: CGAffineTransform(scaleX: sx, y: sy)).cropped(to: extent)
}

func topLeft(_ p: CGPoint) -> [Double] { [Double(p.x), Double(1 - p.y)] }

func topLeftBox(_ r: CGRect) -> [Double] {
    [Double(r.minX), Double(1 - r.maxY), Double(r.maxX), Double(1 - r.minY)]
}

func vision(_ input: String, _ outDir: String) {
    let img = load(input)
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: input), options: [:])
    let person = VNGeneratePersonSegmentationRequest()
    person.qualityLevel = .accurate
    let foreground = VNGenerateForegroundInstanceMaskRequest()
    let rects = VNDetectFaceRectanglesRequest()
    let saliency = VNGenerateAttentionBasedSaliencyImageRequest()
    let horizon = VNDetectHorizonRequest()
    do { try handler.perform([person, foreground, rects, saliency, horizon]) } catch { fail("vision failed: \(error)") }
    let faces = VNDetectFaceLandmarksRequest()
    faces.inputFaceObservations = rects.results ?? []
    if !(rects.results ?? []).isEmpty {
        do { try handler.perform([faces]) } catch { fail("vision failed: \(error)") }
    }

    var info: [String: Any] = [:]
    if let pb = person.results?.first?.pixelBuffer {
        writeMask(scaled(CIImage(cvPixelBuffer: pb), to: img.extent), outDir + "/person.png")
        info["person"] = true
    }
    if let r = foreground.results?.first, !r.allInstances.isEmpty,
       let pb = try? r.generateScaledMaskForImage(forInstances: r.allInstances, from: handler) {
        writeMask(CIImage(cvPixelBuffer: pb), outDir + "/subject.png")
        info["subject_instances"] = r.allInstances.count
    }
    info["faces"] = (faces.results ?? []).map { f -> [String: Any] in
        var face: [String: Any] = ["box": topLeftBox(f.boundingBox), "confidence": f.confidence]
        func pts(_ region: VNFaceLandmarkRegion2D?) -> [[Double]]? {
            guard let region else { return nil }
            return region.normalizedPoints.map { p in
                topLeft(CGPoint(x: f.boundingBox.minX + p.x * f.boundingBox.width,
                                y: f.boundingBox.minY + p.y * f.boundingBox.height))
            }
        }
        if let l = f.landmarks {
            face["left_pupil"] = pts(l.leftPupil)?.first
            face["right_pupil"] = pts(l.rightPupil)?.first
            face["left_eye"] = pts(l.leftEye)
            face["right_eye"] = pts(l.rightEye)
            face["outer_lips"] = pts(l.outerLips)
        }
        return face
    }
    info["salient_boxes"] = (saliency.results?.first?.salientObjects ?? []).map { topLeftBox($0.boundingBox) }
    if let h = horizon.results?.first { info["horizon_degrees"] = Double(h.angle) * 180 / .pi }
    writeJSON(info, outDir + "/vision.json")
}

func num(_ d: [String: Any], _ k: String, _ def: Double = 0) -> Double { (d[k] as? NSNumber)?.doubleValue ?? def }

func loadFloats(_ path: String) -> Data {
    guard let data = FileManager.default.contents(atPath: path) else { fail("missing LUT: \(path)") }
    return data
}

func apply(_ op: [String: Any], to img: CIImage, base: URL, space: CGColorSpace) -> CIImage {
    let extent = img.extent
    switch op["op"] as? String {
    case "matrix":
        let f = CIFilter.colorMatrix()
        f.inputImage = img
        f.rVector = CIVector(x: num(op, "r", 1), y: 0, z: 0, w: 0)
        f.gVector = CIVector(x: 0, y: num(op, "g", 1), z: 0, w: 0)
        f.bVector = CIVector(x: 0, y: 0, z: num(op, "b", 1), w: 0)
        return f.outputImage!
    case "exposure":
        let f = CIFilter.exposureAdjust()
        f.inputImage = img
        f.ev = Float(num(op, "ev"))
        return f.outputImage!
    case "highlight_shadow":
        let f = CIFilter.highlightShadowAdjust()
        f.inputImage = img.clampedToExtent()
        f.shadowAmount = Float(num(op, "shadow"))
        f.highlightAmount = Float(num(op, "highlight", 1))
        f.radius = Float(num(op, "radius"))
        return f.outputImage!.cropped(to: extent)
    case "curves":
        let f = CIFilter.colorCurves()
        f.inputImage = img
        f.curvesData = loadFloats(base.appendingPathComponent(op["lut"] as! String).path)
        f.curvesDomain = CIVector(x: 0, y: 1)
        f.colorSpace = space
        return f.outputImage!
    case "cube":
        let f = CIFilter.colorCubeWithColorSpace()
        f.inputImage = img
        f.cubeDimension = Float(num(op, "dim"))
        f.cubeData = loadFloats(base.appendingPathComponent(op["lut"] as! String).path)
        f.colorSpace = space
        return f.outputImage!
    case "vibrance":
        let f = CIFilter.vibrance()
        f.inputImage = img
        f.amount = Float(num(op, "amount"))
        return f.outputImage!
    case "saturation":
        let f = CIFilter.colorControls()
        f.inputImage = img
        f.saturation = Float(num(op, "value", 1))
        return f.outputImage!
    case "sharpen":
        let f = CIFilter.sharpenLuminance()
        f.inputImage = img.clampedToExtent()
        f.sharpness = Float(num(op, "sharpness"))
        f.radius = Float(num(op, "radius", 1.5))
        return f.outputImage!.cropped(to: extent)
    default:
        fail("unknown op: \(op)")
    }
}

func render(_ planPath: String) {
    let planURL = URL(fileURLWithPath: planPath)
    let base = planURL.deletingLastPathComponent()
    guard let data = try? Data(contentsOf: planURL),
          let plan = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { fail("bad plan: \(planPath)") }

    let space = plan["p3"] as? Bool == true ? p3 : srgb
    var img = load(base.appendingPathComponent(plan["input"] as! String).path)
    let extent = img.extent

    for step in plan["steps"] as? [[String: Any]] ?? [] {
        var adjusted = img
        for op in step["ops"] as? [[String: Any]] ?? [] { adjusted = apply(op, to: adjusted, base: base, space: space) }
        if let maskName = step["mask"] as? String {
            let mask = loadMask(base.appendingPathComponent(maskName).path)
            let blend = CIFilter.blendWithMask()
            blend.inputImage = adjusted
            blend.backgroundImage = img
            blend.maskImage = scaled(mask, to: extent)
            img = blend.outputImage!.cropped(to: extent)
        } else {
            img = adjusted.cropped(to: extent)
        }
    }

    if let c = plan["crop"] as? [NSNumber], c.count == 4 {
        let (x, y, w, h) = (c[0].doubleValue, c[1].doubleValue, c[2].doubleValue, c[3].doubleValue)
        let rect = CGRect(x: x, y: extent.height - y - h, width: w, height: h)
        img = img.cropped(to: rect).transformed(by: CGAffineTransform(translationX: -rect.minX, y: -rect.minY))
    }
    if let r = plan["resize"] as? [NSNumber], r.count == 2 {
        let scale = r[1].doubleValue / img.extent.height
        let f = CIFilter.lanczosScaleTransform()
        f.inputImage = img.clampedToExtent()
        f.scale = Float(scale)
        f.aspectRatio = Float((r[0].doubleValue / img.extent.width) / scale)
        img = f.outputImage!.cropped(to: CGRect(x: 0, y: 0, width: r[0].doubleValue, height: r[1].doubleValue))
    }
    if let v = plan["vignette"] as? [String: Any] {
        let e = img.extent
        let f = CIFilter.vignetteEffect()
        f.inputImage = img
        f.center = CGPoint(x: e.midX, y: e.midY)
        f.radius = Float(num(v, "radius") * hypot(e.width, e.height) / 2)
        f.intensity = Float(num(v, "intensity"))
        f.falloff = Float(num(v, "falloff", 0.5))
        img = f.outputImage!.cropped(to: e)
    }

    img = img.settingProperties([:])
    let out = URL(fileURLWithPath: plan["output"] as! String)
    let quality = num(plan, "quality", 0.95)
    do {
        if out.pathExtension.lowercased() == "png" {
            try ctx.writePNGRepresentation(of: img, to: out, format: .RGBA16, colorSpace: space)
        } else {
            try ctx.writeJPEGRepresentation(of: img, to: out, colorSpace: space,
                options: [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): quality])
        }
    } catch { fail("write failed: \(error)") }
    print(out.path)
}

let args = CommandLine.arguments
switch args.count > 1 ? args[1] : "" {
case "decode" where args.count == 4: decode(args[2], args[3])
case "vision" where args.count == 4: vision(args[2], args[3])
case "render" where args.count == 3: render(args[2])
default: fail("usage: feedready-engine decode IN OUT.png | vision IN OUTDIR | render PLAN.json")
}
