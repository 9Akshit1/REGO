#! Flux2D 25.1
newProject()

SketcherOption[1].magnetizationGrid=MagnetizationGrid(gridActivation='OUI',lengthGridCell=10.0,cellSubdivision=10,subdivisionPoint=10)

openSketcher2dContext()

closeSketcher2dContext()

buildFaces()

lastInstance = ApplicationMagneticDC2D(domain2D=Domain2DPlane(lengthUnit=LengthUnit['MILLIMETER'],
                                               depth='100'),
                        coilCoefficient=CoilCoefficientAutomatic())

lastInstance = ParameterGeom(name='CW : Coil Width',
              expression='20')

lastInstance = ParameterGeom(name='DO : Depth of Domain',
              expression='100')

lastInstance = ParameterGeom(name='A : Airgap',
              expression='5')

ParameterGeom['DO'].name='DD : Depth of Domain'


Application[2].domain2D=Domain2DPlane(lengthUnit=LengthUnit['MILLIMETER'],
                                      depth='DD')


lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['125',
                      '125'],
                 nature=Nature['STANDARD'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['125',
                      '-125'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['275',
                      '-225'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['275',
                      '225'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-275',
                      '225'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-125',
                      '-125'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-125',
                      '125'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-275',
                      '-225'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-125+CW',
                      '100'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-125+CW',
                      '-100'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-125',
                      '-100'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-125',
                      '100'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

ParameterGeom['A'].name='G : Airgap'


lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['125',
                      'G'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['125',
                      '-G'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['275',
                      '-G'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['275',
                      'G'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-275-CW',
                      '100'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-275',
                      '100'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-275',
                      '-100'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = PointCoordinates(color=Color['Grey'],
                 visibility=Visibility['VISIBLE'],
                 coordSys=CoordSys['XY1'],
                 uvw=['-275-CW',
                      '-100'],
                 nature=Nature['STANDARD'],
                 mesh=MeshPoint['AIDED_MESHPOINT'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[5],
                      Point[18]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[18],
                      Point[19]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[8],
                      Point[19]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[8],
                      Point[3]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[3],
                      Point[15]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[5],
                      Point[4]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[4],
                      Point[16]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[7],
                      Point[1]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[2],
                      Point[6]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[6],
                      Point[11]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[10],
                      Point[11]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[12],
                      Point[7]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[12],
                      Point[9]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[12],
                      Point[11]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[9],
                      Point[10]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[1],
                      Point[13]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[2],
                      Point[14]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[16],
                      Point[13]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[15],
                      Point[14]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[17],
                      Point[18]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[19],
                      Point[20]],
            nature=Nature['STANDARD'])

lastInstance = LineSegment(color=Color['Grey'],
            visibility=Visibility['VISIBLE'],
            defPoint=[Point[20],
                      Point[17]],
            nature=Nature['STANDARD'])

buildFaces()

lastInstance = InfiniteBoxDisc(DISCOID=['800',
                         '1000'])

InfiniteBoxDisc['InfiniteBoxDisc'].complete2D(buildingOption='Faces',
           coordSys=CoordSys['XY1'],
           linkMesh='LinkMesh')

AidedMesh[1].synchronize()

meshDomain()

importMaterial(fileName='C:/Program Files/Altair/2025.1/flux/Materials/FLUX_111_MATERI.DAT', materialNames=['FLU_COPPER           :'])
Material(name='FLU_M270_35A', propertyBH=PropertyBhNonlinearSpline(splinePoints=[BHPoint(h=0.0, b=0.0), BHPoint(h=29.38, b=0.1), BHPoint(h=37.39, b=0.2), BHPoint(h=45.24, b=0.3), BHPoint(h=50.18, b=0.4), BHPoint(h=55.45, b=0.5), BHPoint(h=62.07, b=0.6), BHPoint(h=70.32, b=0.7), BHPoint(h=81.92, b=0.8), BHPoint(h=96.58, b=0.9), BHPoint(h=118.68, b=1.0), BHPoint(h=155.51, b=1.1), BHPoint(h=226.67, b=1.2), BHPoint(h=416.07, b=1.3), BHPoint(h=1059.27, b=1.4), BHPoint(h=2756.65, b=1.5), BHPoint(h=5441.9, b=1.59), BHPoint(h=7069.65, b=1.64), BHPoint(h=8213.34, b=1.67), BHPoint(h=10000.0, b=1.723), BHPoint(h=20000.0, b=1.859), BHPoint(h=30000.0, b=1.922), BHPoint(h=50000.0, b=1.991), BHPoint(h=100000.0, b=2.089), BHPoint(h=200000.0, b=2.233), BHPoint(h=300000.0, b=2.365)], equivalentHarmonicCurve=EquivalentBhUnmodified()))

lastInstance = RegionFace(name='Air',
           magneticDC2D=MagneticDC2DFaceVacuum(),
           visibility=Visibility['VISIBLE'])

RegionFace['AIR'].color=Color['White']


lastInstance = RegionFace(name='Coil_N',
           magneticDC2D=MagneticDC2DFaceVacuum(),
           visibility=Visibility['VISIBLE'],
           color=Color['Pink'])

lastInstance = RegionFace(name='COIL_P',
           magneticDC2D=MagneticDC2DFaceVacuum(),
           visibility=Visibility['VISIBLE'],
           color=Color['Magenta'])

lastInstance = RegionFace(name='CORE',
           magneticDC2D=MagneticDC2DFaceMagnetic(material=Material['FLU_M270_35A']),
           visibility=Visibility['VISIBLE'],
           color=Color['Turquoise'])

RegionFace['INFINITE'].color=Color['White']


lastInstance = VariationParameterPilot(name='I',
                        referenceValue=1.0)

lastInstance = VariationParameterPilot(name='N',
                        referenceValue=300.0)

lastInstance = CoilConductorImposedCurrent(name='CoilConductor_1',
                            rmsModulus='I')

RegionFace['COIL_N'].magneticDC2D=MagneticDC2DFaceCoilConductor(coilConductor=CoilConductor2DNegative(turnNumber='N',
                                                                                                      seriesParallel=AllInSeries(),
                                                                                                      electricComponent=CoilConductor['COILCONDUCTOR_1']))


RegionFace['COIL_P'].magneticDC2D=MagneticDC2DFaceCoilConductor(coilConductor=CoilConductor2DPositive(turnNumber='N',
                                                                                                      seriesParallel=AllInSeries(),
                                                                                                      electricComponent=CoilConductor['COILCONDUCTOR_1']))


assignRegionToFaces(face=[Face[4]],
                    region=RegionFace['AIR'])

assignRegionToFaces(face=[Face[1]],
                    region=RegionFace['CORE'])

assignRegionToFaces(face=[Face[2]],
                    region=RegionFace['COIL_P'])

assignRegionToFaces(face=[Face[3]],
                    region=RegionFace['COIL_N'])

result = checkPhysic()

Scenario(name='Change_Airgap',
         adaptive=InactivatedAdaptive())

startMacroTransaction()

Scenario['Change_Airgap'].addPilot(pilot=MultiValues(parameter=VariationParameter['G'],
                                                     intervals=[IntervalStepValue(minValue=1.0,
                                                                                  maxValue=5.0,
                                                                                  stepValue=1.0)]))

endMacroTransaction()

Scenario['Change_Airgap'].printConfiguration(mode=-1)

