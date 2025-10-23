// ===========================================================================
// MagneticForce.h - Header File
// EDEM Particle Body Force API for Magnetic Field Coupling
// ===========================================================================

#ifndef MAGNETIC_FORCE_H
#define MAGNETIC_FORCE_H

#include "IPluginParticleBodyForce.h"
#include "IPluginParticleBodyForceV3_9_0.h"
#include <vector>
#include <string>
#include <cmath>

class CMagneticForce : public virtual IPluginParticleBodyForceV3_9_0
{
public:
    CMagneticForce();
    
    // Setup methods (called once at simulation start)
    virtual bool setup(
        NApiHelpers::CFlags<EApiExternalForceFeatureFlags>& featureFlags,
        NApiHelpers::CFlags<NApi::EApiSolverFlags>& solverFlags,
        NApiHelpers::CFlags<NApi::EApiParticleShapeFlags>& particleShapeFlags,
        NApiHelpers::CSimpleString& physicsModelName,
        const char prefFile[],
        char customMsg[NApi::ERROR_MSG_MAX_LENGTH]);
    
    virtual void setApiParametersTemplate() const;
    
    virtual bool starting(
        int numThreads,
        char guiPath[NApi::GUI_FILE_MAX_LENGTH]);
    
    virtual bool stopping();
    
    // Simulation methods (called each timestep)
    virtual ECalculateResult externalForce(
        int threadID,
        const NExternalForceTypes::STimeStepData& timeStepData,
        const NExternalForceTypes::SParticle& particle,
        NApiCore::ICustomPropertyDataApi_1_0* particleCustomProperties,
        NApiCore::ICustomPropertyDataApi_1_0* simulationCustomProperties,
        NExternalForceTypes::SResults& results);
    
private:
    // Field data structures
    struct FieldPoint {
        double x, y;           // Position [m]
        double Bx, By;         // Field components [T]
        double gradBx, gradBy; // Force gradients [T²/m]
    };
    
    std::vector<FieldPoint> m_fieldData;
    
    // Grid structure for fast lookup
    std::vector<double> m_xGrid;
    std::vector<double> m_yGrid;
    int m_nx, m_ny;
    double m_xMin, m_xMax, m_yMin, m_yMax;
    double m_dx, m_dy;
    
    // Parameters
    double m_activationTime;
    double m_mu0;
    std::string m_chiPropertyName;
    std::string m_fieldFileName;
    
    // Methods
    bool loadFieldData(const char* filename);
    bool interpolateForce(double x, double y, double& gradBx, double& gradBy);
    void cropFieldToCoilRegion();
};

#endif // MAGNETIC_FORCE_H