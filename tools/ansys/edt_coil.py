# ----------------------------------------------
# Script Recorded by Ansys Electronics Desktop Student Version 2025.2.0
# 8:44:39  Nov 04, 2025
# ----------------------------------------------
import ScriptEnv
ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
oDesktop.RestoreWindow()
oProject = oDesktop.SetActiveProject("Coil")
oDesign = oProject.SetActiveDesign("Maxwell3DDesign1")
oModule = oDesign.GetModule("MeshSetup")
oModule.AssignLengthOp(
	[
		"NAME:Box",
		"RefineInside:="	, True,
		"Enabled:="		, True,
		"Objects:="		, ["Box1"],
		"RestrictElem:="	, False,
		"NumMaxElem:="		, "1000",
		"RestrictLength:="	, True,
		"MaxLength:="		, "15mm"
	])
oModule.AssignLengthOp(
	[
		"NAME:Coil",
		"RefineInside:="	, False,
		"Enabled:="		, True,
		"Objects:="		, ["PolygonHelix1"],
		"RestrictElem:="	, False,
		"NumMaxElem:="		, "1000",
		"RestrictLength:="	, True,
		"MaxLength:="		, "10mm"
	])
oProject.Save()
oModule = oDesign.GetModule("AnalysisSetup")
oModule.InsertSetup("Magnetostatic", 
	[
		"NAME:Setup1",
		"Enabled:="		, True,
		[
			"NAME:MeshLink",
			"ImportMesh:="		, False
		],
		"MaximumPasses:="	, 10,
		"MinimumPasses:="	, 2,
		"MinimumConvergedPasses:=", 1,
		"PercentRefinement:="	, 30,
		"SolveFieldOnly:="	, False,
		"PercentError:="	, 5,
		"SolveMatrixAtLast:="	, True,
		"UseNonLinearIterNum:="	, False,
		"UseIterativeSolver:="	, True,
		"RelativeResidual:="	, 1E-06,
		"NonLinearResidual:="	, 0.001,
		"RelaxationFactor:="	, 1,
		"SmoothBHCurve:="	, False,
		[
			"NAME:MuOption",
			"MuNonLinearBH:="	, True
		]
	])
oProject.Save()
oDesign.AnalyzeAll()
oProject.Save()
oDesign.AnalyzeAll()
oProject.Save()
oDesign.AnalyzeAll()
oEditor = oDesign.SetActiveEditor("3D Modeler")
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DPolylineTab",
			[
				"NAME:PropServers", 
				"Polyline1:CreatePolyline:1:Segment1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Point2",
					"X:="			, "50mm",
					"Y:="			, "3mm",
					"Z:="			, "20.500148414343mm"
				]
			]
		]
	])
oDesign.Undo()
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box1:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:XSize",
					"Value:="		, "Lb/2"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box1:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:YSize",
					"Value:="		, "Lb/2"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box1:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:ZSize",
					"Value:="		, "Lb/2"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box1:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Position",
					"X:="			, "-Lb/4",
					"Y:="			, "-Lb/4",
					"Z:="			, "-Lb/4+10mm"
				]
			]
		]
	])
oDesign.Undo()
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box1:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Position",
					"X:="			, "-Lb/4",
					"Y:="			, "-Lb/4",
					"Z:="			, "-Lb/4+10mm"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box2:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:XSize",
					"Value:="		, "50mm"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box2:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:YSize",
					"Value:="		, "-50mm"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box2:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:ZSize",
					"Value:="		, "Lb/2"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box2:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:YSize",
					"Value:="		, "-Lb/2"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box2:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:XSize",
					"Value:="		, "Lb/2"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DCmdTab",
			[
				"NAME:PropServers", 
				"Box2:CreateBox:1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Position",
					"X:="			, "Lb/4",
					"Y:="			, "Lb/4",
					"Z:="			, "-Lb/4+10"
				]
			]
		]
	])
oDesign.Undo()
oDesign.Redo()
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DPolylineTab",
			[
				"NAME:PropServers", 
				"Polyline1:CreatePolyline:1:Segment1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Point2",
					"X:="			, "10mm",
					"Y:="			, "3mm",
					"Z:="			, "20.500148414343mm"
				]
			]
		]
	])
oDesign.Undo()
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DPolylineTab",
			[
				"NAME:PropServers", 
				"Polyline2:CreatePolyline:1:Segment1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Point2",
					"X:="			, "50mm",
					"Y:="			, "-3mm",
					"Z:="			, "0.0011133914768455mm"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DPolylineTab",
			[
				"NAME:PropServers", 
				"Polyline2:CreatePolyline:1:Segment1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Point2",
					"X:="			, "25mm",
					"Y:="			, "-3mm",
					"Z:="			, "0.0011133914768455mm"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DPolylineTab",
			[
				"NAME:PropServers", 
				"Polyline1:CreatePolyline:1:Segment1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Point2",
					"X:="			, "Lb/4",
					"Y:="			, "3mm",
					"Z:="			, "20.500148414343mm"
				]
			]
		]
	])
oEditor.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:Geometry3DPolylineTab",
			[
				"NAME:PropServers", 
				"Polyline2:CreatePolyline:1:Segment1"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Point2",
					"X:="			, "Lb/4",
					"Y:="			, "-3mm",
					"Z:="			, "0.0011133914768455mm"
				]
			]
		]
	])
oModule = oDesign.GetModule("BoundarySetup")
oModule.AssignCurrent(
	[
		"NAME:I1_in",
		"Faces:="		, [223],
		"Current:="		, "1A",
		"IsSolid:="		, False,
		"Point out of terminal:=", False
	])
oModule.AssignCurrent(
	[
		"NAME:I1_out",
		"Faces:="		, [237],
		"Current:="		, "1A",
		"IsSolid:="		, False,
		"Point out of terminal:=", True
	])
oProject.Save()
oDesign.AnalyzeAll()
oModule = oDesign.GetModule("FieldsReporter")
oModule.CreateFieldPlot(
	[
		"NAME:H_Vector1",
		"SolutionName:="	, "Setup1 : LastAdaptive",
		"UserSpecifyName:="	, 0,
		"UserSpecifyFolder:="	, 0,
		"QuantityName:="	, "H_Vector",
		"PlotFolder:="		, "H",
		"StreamlinePlot:="	, False,
		"AdjacentSidePlot:="	, False,
		"FullModelPlot:="	, False,
		"IntrinsicVar:="	, "",
		"PlotGeomInfo:="	, [1,"Surface","CutPlane",1,"Global:XZ"],
		"FilterBoxes:="		, [0],
		[
			"NAME:PlotOnSurfaceSettings",
			"ShadingType:="		, 0,
			"Filled:="		, False,
			"IsoValType:="		, "Tone",
			"AddGrid:="		, False,
			"MapTransparency:="	, True,
			"Refinement:="		, 0,
			"Transparency:="	, 0,
			"SmoothingLevel:="	, 0,
			[
				"NAME:Arrow3DSpacingSettings",
				"ArrowUniform:="	, True,
				"ArrowSpacing:="	, 0,
				"MinArrowSpacing:="	, 0,
				"MaxArrowSpacing:="	, 0
			],
			"GridColor:="		, [255,255,255]
		],
		"EnableGaussianSmoothing:=", False,
		"SurfaceOnly:="		, False
	], "Field")
oModule.CreateFieldPlot(
	[
		"NAME:Mag_B1",
		"SolutionName:="	, "Setup1 : LastAdaptive",
		"UserSpecifyName:="	, 0,
		"UserSpecifyFolder:="	, 0,
		"QuantityName:="	, "Mag_B",
		"PlotFolder:="		, "B",
		"StreamlinePlot:="	, False,
		"AdjacentSidePlot:="	, False,
		"FullModelPlot:="	, False,
		"IntrinsicVar:="	, "",
		"PlotGeomInfo:="	, [1,"Surface","CutPlane",1,"Global:YZ"],
		"FilterBoxes:="		, [0],
		[
			"NAME:PlotOnSurfaceSettings",
			"ShadingType:="		, 0,
			"Filled:="		, False,
			"IsoValType:="		, "Tone",
			"AddGrid:="		, False,
			"MapTransparency:="	, True,
			"Refinement:="		, 0,
			"Transparency:="	, 0,
			"SmoothingLevel:="	, 0,
			[
				"NAME:Arrow3DSpacingSettings",
				"ArrowUniform:="	, True,
				"ArrowSpacing:="	, 0,
				"MinArrowSpacing:="	, 0,
				"MaxArrowSpacing:="	, 0
			],
			"GridColor:="		, [255,255,255]
		],
		"EnableGaussianSmoothing:=", False,
		"SurfaceOnly:="		, False
	], "Field")
oDesign.ChangeProperty(
	[
		"NAME:AllTabs",
		[
			"NAME:MeshSetupTab",
			[
				"NAME:PropServers", 
				"MeshSetup:Box"
			],
			[
				"NAME:ChangedProps",
				[
					"NAME:Max Length",
					"Value:="		, "10mm"
				]
			]
		]
	])
oProject.Save()
oDesign.AnalyzeAll()
oModule.SaveFieldsPlots(["H_Vector1"], "C:\\Users\\eruku\\Akshith\\REGO\\Ansys\\hehe.dsp")
