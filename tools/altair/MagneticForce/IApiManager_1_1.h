#ifndef IAPIMANAGER_1_1_H
#define IAPIMANAGER_1_1_H

#include "IApiManager_1_0.h"
#include "IApiPluginParameterManager_1_1.h"
#include "IContactManagerApi_1_0.h"
#include "ICustomPropertyManagerApi_1_0.h"
#include "IFieldManagerApi_1_1.h"
#include "IGeometryManagerApi_1_4.h"
#include "IParticleManagerApi_1_7.h"
#include "ISimulationManagerApi_1_3.h"
#include "ICounterPropertyManagerApi_1_0.h"

namespace NApiCore
{
    /**
     * The API manager provides the ability to allocate and initialise various APIs for
     * use by plugins.
     *
     * NAME:    API Manager
     * ID:      EApiId::eApiManager (0)
     * VERSION: 1.1
     *
     * All allocation and de-allocation of API instances is handled by the manager.
     *
     * getApi() is used for retrieving allocated and initialized base API instances.
     *
     * NOTE: The API manager is capable of returning instances of any supported version
     * of the API manager.
     */
    class IApiManager_1_1 : public IApiManager_1_0
    {
    public:
        /**
         * Constructor, does nothing.
         */
        IApiManager_1_1() {};

        /**
         * Destructor, does nothing.
         */
        virtual ~IApiManager_1_1() {};

        /**
         * This is called once during the loading of the API to populate the managers
         * with the latest versions.
         */
        virtual void setApiManagers()
        {
            particleManager_1_7 = static_cast<IParticleManagerApi_1_7*> (getApi(eParticleManager, 1, 7));
            geometryManager_1_4 = static_cast<IGeometryManagerApi_1_4*> (getApi(eGeometryManager, 1, 4));
            contactManager_1_0 = static_cast<IContactManagerApi_1_0*> (getApi(eContactManager, 1, 0));
            fieldManager_1_1 = static_cast<IFieldManagerApi_1_1*> (getApi(eFieldManager, 1, 1));
            simulationManager_1_3 = static_cast<ISimulationManagerApi_1_3*> (getApi(eSimulationManager, 1, 3));
            contactCustomPropertyManager_1_0 = static_cast<ICustomPropertyManagerApi_1_0*> (getApi(eContactCustomPropertyManager, 1, 0));
            geometryCustomPropertyManager_1_0 = static_cast<ICustomPropertyManagerApi_1_0*> (getApi(eGeometryCustomPropertyManager, 1, 0));
            particleCustomPropertyManager_1_0 = static_cast<ICustomPropertyManagerApi_1_0*> (getApi(eParticleCustomPropertyManager, 1, 0));
            simulationCustomPropertyManager_1_0 = static_cast<ICustomPropertyManagerApi_1_0*> (getApi(eSimulationCustomPropertyManager, 1, 0));
            parameterManager_1_1 = static_cast<IApiPluginParameterManager_1_1*> (getApi(eApiParameterManager, 1, 1));
            interactionCounterPropertyManager_1_0 = static_cast<ICounterPropertyManagerApi_1_0*> (getApi(eInteractionCounterPropertyManager, 1, 0));
        }

        /**
         * Getters for each manager
         */
        virtual IParticleManagerApi_1_7* getParticleManager() const { return particleManager_1_7; }
        virtual IGeometryManagerApi_1_4* getGeometryManager() const { return geometryManager_1_4; }
        virtual IContactManagerApi_1_0* getContactManager() const { return contactManager_1_0; }
        virtual IFieldManagerApi_1_1* getFieldManager() const { return fieldManager_1_1; }
        virtual ISimulationManagerApi_1_3* getSimulationManager() const { return simulationManager_1_3; }
        virtual ICustomPropertyManagerApi_1_0* getContactCustomPropertyManager() const { return contactCustomPropertyManager_1_0; }
        virtual ICustomPropertyManagerApi_1_0* getGeometryCustomPropertyManager() const { return geometryCustomPropertyManager_1_0; }
        virtual ICustomPropertyManagerApi_1_0* getParticleCustomPropertyManager() const { return particleCustomPropertyManager_1_0; }
        virtual ICustomPropertyManagerApi_1_0* getSimulationCustomPropertyManager() const { return simulationCustomPropertyManager_1_0; }
        virtual IApiPluginParameterManager_1_1* getParameterManager() const { return parameterManager_1_1; }
        virtual ICounterPropertyManagerApi_1_0* getInteractionCounterPropertyManager() const { return interactionCounterPropertyManager_1_0; }

    private:
        IParticleManagerApi_1_7* particleManager_1_7 = nullptr;
        IGeometryManagerApi_1_4* geometryManager_1_4 = nullptr;
        IContactManagerApi_1_0* contactManager_1_0 = nullptr;
        IFieldManagerApi_1_1* fieldManager_1_1 = nullptr;
        ISimulationManagerApi_1_3* simulationManager_1_3 = nullptr;
        ICustomPropertyManagerApi_1_0* contactCustomPropertyManager_1_0 = nullptr;
        ICustomPropertyManagerApi_1_0* geometryCustomPropertyManager_1_0 = nullptr;
        ICustomPropertyManagerApi_1_0* particleCustomPropertyManager_1_0 = nullptr;
        ICustomPropertyManagerApi_1_0* simulationCustomPropertyManager_1_0 = nullptr;
        IApiPluginParameterManager_1_1* parameterManager_1_1 = nullptr;
        ICounterPropertyManagerApi_1_0* interactionCounterPropertyManager_1_0 = nullptr;
    };
};

#endif // IAPIMANAGER_1_1_H
