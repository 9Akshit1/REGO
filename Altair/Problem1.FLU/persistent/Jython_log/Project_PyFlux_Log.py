#! Flux2D 25.1


# Your project log file has become too 
# large and it is unsafe to open in Flux.
# It has been archived as C:\Users\eruku\Akshith\REGO\Altair\Problem1.FLU\persistent\Jython_log\Project_PyFlux_Log_0.py.
# If needed, consider opening it in a high 
# performance dedicated editor.

saveProjectAs('Akshith/REGO/Altair/Problem1.FLU')

Scenario['CHANGE_AIRGAP'].solve(projectName='Akshith/REGO/Altair/Problem1.FLU')

lastInstance = IsovalueSpatialGroup(name='ISOVAL_1',
                     formula='B',
                     forceVisibility='yes',
                     smoothValues='yes',
                     group=[Groupspatial['S_CORE'],
                            Groupspatial['S_AIR']])

selectCurrentStep(activeScenario=Scenario['CHANGE_AIRGAP'],
                  parameterValue=['G=1.0'])

selectCurrentStep(activeScenario=Scenario['CHANGE_AIRGAP'],
                  parameterValue=['G=3.0'])

EvolutiveCurve2D(name='EvolutiveCurve2D_1',
                 evolutivePath=EvolutivePath(parameterSet=[SetParameterXVariable(paramEvol=VariationParameter['G'],
                                                                                 limitMin=1.0,
                                                                                 limitMax=5.0)]),
                 formula=['FluxMag(S_CORE)',
                          'FluxMag(S_AIR)'])

saveProject()

saveProject()

saveProject()

