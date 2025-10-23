#ifndef APIIDS_H
#define APIIDS_H

/***************************************************************************/
/* This header file contains unique id numbers for all supported APIs for  */
/* This version of EDEM.                                                   */
/***************************************************************************/

namespace NApiCore
{
    /**
     * Represents the unique ID for an API
     */
    enum EApiId
    {
        eApiManager                        =  0, /**< API manager */
        eFieldManager                      =  1, /**< Field manager */
        eField                             =  2, /**< Individual field element */
        eLicenseManager                    =  3, /**< License Manager (unsupported) */
        eContactCustomPropertyManager      =  4, /**< Contact Custom Property Manager */
        eGeometryCustomPropertyManager     =  5, /**< Geometry Custom Property Manager */
        eParticleCustomPropertyManager     =  6, /**< Particle Custom Property Manager */
        eSimulationCustomPropertyManager   =  7, /**< Simulation Custom Property Manager */
        eCustomPropertyData                =  8, /**< Custom property data and deltas */
        eParticleManager                   =  9, /**< Particle Manager */
        eGeometryManager                   = 10, /**< Geometry Manager */
        eSimulationManager                 = 11, /**< Simulation Manager */
        eApiParameterManager               = 12, /**< GUI Parameter Manager */
        eContactManager                    = 13, /**< Contact Manager */
        eInteractionCounterPropertyManager = 14, /**< Interaction Counter Property Manager */
        eMaterialManager                   = 15, /**< Material Manager */
        eWarningManager                    = 16  /**< Custom Warnings and Errors Manager */
    };
};

#endif // APIIDS_H
