Attribute VB_Name = "P1_NoseYoke"
'==========================================================================
' PT-JACK-250  —  P1 nose yoke
'
' Generated from docs/jack/cad/python/gen_sw.py. Units in the API are METRES.
'
' HOW TO RUN
'   1. SolidWorks > Tools > Macro > New...  (save as P1_NoseYoke.swp)
'   2. In the VBA editor: File > Import File... and pick this .bas
'   3. Run Sub main
'
' The macro creates a NEW part and builds the feature tree. Late binding is
' used throughout so no type-library reference is required, and reference
' planes are picked by position rather than by name, so it works on any
' language template.
'
' NOT TESTED AGAINST A LIVE SOLIDWORKS INSTALL — see cad/README.md. If a
' call fails, the STEP file of the same part is the fallback.
'==========================================================================
Option Explicit

Dim swApp As Object
Dim swModel As Object

Private Function NewPartDoc() As Object
    Dim tpl As String
    tpl = swApp.GetUserPreferenceStringValue(8)      'swDefaultTemplatePart
    Set NewPartDoc = swApp.NewDocument(tpl, 0, 0, 0)
End Function

Private Function SelectPlane(ByVal idx As Integer) As Boolean
    'idx 1 = Front, 2 = Top, 3 = Right (order is template-independent)
    Dim swFeat As Object, n As Integer
    Set swFeat = swModel.FirstFeature
    n = 0
    Do While Not swFeat Is Nothing
        If swFeat.GetTypeName2 = "RefPlane" Then
            n = n + 1
            If n = idx Then
                SelectPlane = swFeat.Select2(False, 0)
                Exit Function
            End If
        End If
        Set swFeat = swFeat.GetNextFeature
    Loop
    SelectPlane = False
End Function

Private Sub SelectLastFeature()
    Dim swFeat As Object
    Set swFeat = swModel.FeatureByPositionReverse(0)
    swFeat.Select2 False, -1
End Sub

Sub main()
    Dim i As Integer
    Set swApp = Application.SldWorks
    Set swModel = NewPartDoc()
    If swModel Is Nothing Then
        MsgBox "No part template found. Set one in Tools > Options > File Locations."
        Exit Sub
    End If

    '--- base profile, extruded 75.0 mm -------------------------------------
    swModel.ClearSelection2 True
    SelectPlane 1
    swModel.SketchManager.InsertSketch True
    swModel.SketchManager.CreateLine -0.125000, 0.065000, 0#, -0.105000, 0.085000, 0#
    swModel.SketchManager.CreateLine -0.105000, 0.085000, 0#, 0.105000, 0.085000, 0#
    swModel.SketchManager.CreateLine 0.105000, 0.085000, 0#, 0.125000, 0.065000, 0#
    swModel.SketchManager.CreateLine 0.125000, 0.065000, 0#, 0.125000, -0.020000, 0#
    swModel.SketchManager.CreateLine 0.125000, -0.020000, 0#, 0.041000, -0.020000, 0#
    swModel.SketchManager.CreateLine 0.041000, -0.020000, 0#, 0.041000, -0.085000, 0#
    swModel.SketchManager.CreateLine 0.041000, -0.085000, 0#, 0.011000, -0.085000, 0#
    swModel.SketchManager.CreateLine 0.011000, -0.085000, 0#, 0.011000, -0.020000, 0#
    swModel.SketchManager.CreateLine 0.011000, -0.020000, 0#, 0.011000, 0.000000, 0#
    swModel.SketchManager.CreateArc 0#, 0#, 0#, 0.011000, 0#, 0#, -0.011000, 0#, 0#, 1
    swModel.SketchManager.CreateLine -0.011000, 0.000000, 0#, -0.011000, -0.020000, 0#
    swModel.SketchManager.CreateLine -0.011000, -0.020000, 0#, -0.011000, -0.085000, 0#
    swModel.SketchManager.CreateLine -0.011000, -0.085000, 0#, -0.041000, -0.085000, 0#
    swModel.SketchManager.CreateLine -0.041000, -0.085000, 0#, -0.041000, -0.020000, 0#
    swModel.SketchManager.CreateLine -0.041000, -0.020000, 0#, -0.125000, -0.020000, 0#
    swModel.SketchManager.CreateLine -0.125000, -0.020000, 0#, -0.125000, 0.065000, 0#
    swModel.SketchManager.InsertSketch True
    swModel.ClearSelection2 True
    SelectLastFeature
    swModel.FeatureManager.FeatureExtrusion2 True, False, False, 0, 0, 0.075000, 0.01, _
        False, False, False, False, 0.0174532925199433, 0.0174532925199433, _
        False, False, False, False, True, True, True, 0, 0, False

    '--- rod seats M24x1.5 - tapping drill 22.5, THROUGH (tap 45 deep) 
    swModel.ClearSelection2 True
    SelectPlane 1
    swModel.SketchManager.InsertSketch True
    swModel.SketchManager.CreateCircleByRadius -0.080000, 0.000000, 0#, 0.011250
    swModel.SketchManager.CreateCircleByRadius 0.080000, 0.000000, 0#, 0.011250
    swModel.SketchManager.InsertSketch True
    swModel.ClearSelection2 True
    SelectLastFeature
    swModel.FeatureManager.FeatureCut4 False, False, True, 1, 1, 0.01, 0.01, _
        False, False, False, False, 0.0174532925199433, 0.0174532925199433, _
        False, False, False, False, False, True, True, True, True, True, _
        False, 0, 0, False
    '--- bearing-pad fixing holes M8 - tapping drill 6.8, 18 deep ----
    swModel.ClearSelection2 True
    SelectPlane 1
    swModel.SketchManager.InsertSketch True
    swModel.SketchManager.CreateCircleByRadius -0.026000, -0.018000, 0#, 0.003400
    swModel.SketchManager.CreateCircleByRadius -0.026000, 0.018000, 0#, 0.003400
    swModel.SketchManager.CreateCircleByRadius 0.026000, -0.018000, 0#, 0.003400
    swModel.SketchManager.CreateCircleByRadius 0.026000, 0.018000, 0#, 0.003400
    swModel.SketchManager.InsertSketch True
    swModel.ClearSelection2 True
    SelectLastFeature
    swModel.FeatureManager.FeatureCut4 True, False, False, 0, 0, 0.018000, 0.01, _
        False, False, False, False, 0.0174532925199433, 0.0174532925199433, _
        False, False, False, False, False, True, True, True, True, True, _
        False, 0, 0, False

    swModel.ViewZoomtofit2
    swModel.ClearSelection2 True
    MsgBox "P1 nose yoke built." & vbCrLf & _
           "Still to add by hand: tapped-thread callouts, the lightening pockets," & vbCrLf & _
           "and R8 fillets on internal corners (see cad/README.md)."
End Sub
